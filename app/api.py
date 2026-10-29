from __future__ import annotations

import hmac
import csv
import io
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ingest import VENUES
from .models import Job, JobEvent, Paper, PaperBatch, PaperSource, Source, now
from .db import SessionLocal, seed_sources
from .datasets import DATASET_ID, ImportConflict, import_sample, load_sample
from scripts.fetch_openalex_batch import SOURCES as OPENALEX_SOURCES

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_sources()
    yield


app = FastAPI(title="Tupu data management", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if origin.strip()],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


def db_session():
    with SessionLocal() as db:
        yield db


def is_local_demo(request: Request) -> bool:
    return os.getenv("LOCAL_DEMO") == "1" and request.client is not None and request.client.host in {"127.0.0.1", "::1"}


def admin(request: Request, authorization: str | None = Header(default=None)):
    if is_local_demo(request):
        return
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Administrator token required")
    if not hmac.compare_digest(authorization[7:], expected):
        raise HTTPException(403, "Invalid administrator token")


class SourceUpdate(BaseModel):
    enabled: bool
    page_size: int = Field(ge=1, le=1000)
    max_retries: int = Field(ge=1, le=8)


class JobCreate(BaseModel):
    venue: str
    year: int = Field(ge=1980, le=2100)
    source: Literal["auto", "dblp", "openalex"] = "auto"


class SampleImport(BaseModel):
    dataset_id: str = DATASET_ID


class JobView(BaseModel):
    id: int
    batch_id: int
    batch_code: str
    kind: str
    dataset_id: str | None
    venue: str
    year: int
    source: str
    status: str
    stage: str
    attempted: int
    succeeded: int
    failed: int
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SampleImportView(JobView):
    paper_count: int
    total_papers: int


def job_data(job: Job) -> dict:
    return {"id": job.id, "batch_id": job.id, "batch_code": f"BATCH-{job.id:06d}",
            "kind": job.kind, "dataset_id": job.dataset_id,
            "venue": job.venue, "year": job.year, "source": job.source, "status": job.status, "stage": job.stage,
            "attempted": job.attempted, "succeeded": job.succeeded, "failed": job.failed,
            "error": job.error, "created_at": job.created_at, "updated_at": job.updated_at,
            "started_at": job.started_at, "finished_at": job.finished_at}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/runtime")
def runtime(request: Request):
    return {"local_demo": is_local_demo(request)}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return Path(__file__).with_name("admin.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def preview_page():
    return Path(__file__).with_name("index.html").read_text(encoding="utf-8")


def paper_data(paper: Paper, include_abstract: bool = True, batch_ids: list[int] | None = None) -> dict:
    result = {"id": paper.id, "canonical_key": paper.canonical_key,
              "openalex_id": paper.openalex_id, "dblp_key": paper.dblp_key,
              "doi": paper.doi, "title": paper.title, "authors": json.loads(paper.authors_json),
              "venue": paper.venue, "year": paper.year, "source_url": paper.source_url,
              "cited_by_count": paper.cited_by_count, "updated_at": paper.updated_at,
              "batch_ids": batch_ids or []}
    if include_abstract:
        result["abstract"] = paper.abstract
    return result


def batch_map(db: Session, paper_ids: list[int]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    if paper_ids:
        for paper_id, job_id in db.execute(select(PaperBatch.paper_id, PaperBatch.job_id)
                                           .where(PaperBatch.paper_id.in_(paper_ids)).order_by(PaperBatch.job_id)):
            result.setdefault(paper_id, []).append(job_id)
    return result


def paper_filter(venue: str | None, year: int | None, q: str | None = None, batch_id: int | None = None):
    conditions = []
    if venue:
        venue = venue.upper()
        if venue not in VENUES:
            raise HTTPException(422, "Supported venues: CVPR, ICCV, ECCV")
        conditions.append(Paper.venue == venue)
    if year:
        conditions.append(Paper.year == year)
    if batch_id is not None:
        conditions.append(Paper.id.in_(select(PaperBatch.paper_id).where(PaperBatch.job_id == batch_id)))
    if q and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + term + "%"
        conditions.append(or_(Paper.title.ilike(pattern, escape="\\"), Paper.abstract.ilike(pattern, escape="\\")))
    return conditions


@app.get("/api/papers")
def list_papers(q: str | None = Query(default=None, max_length=200), venue: str | None = None,
                year: int | None = Query(default=None, ge=1980, le=2100),
                page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100),
                batch_id: int | None = Query(default=None, ge=1),
                db: Session = Depends(db_session)):
    conditions = paper_filter(venue, year, q, batch_id)
    total = db.scalar(select(func.count(Paper.id)).where(*conditions))
    papers = db.scalars(select(Paper).where(*conditions).order_by(Paper.id)
                        .offset((page - 1) * page_size).limit(page_size)).all()
    batches = batch_map(db, [paper.id for paper in papers])
    return {"total": total, "page": page, "page_size": page_size,
            "items": [paper_data(paper, include_abstract=False, batch_ids=batches.get(paper.id)) for paper in papers]}


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: int, db: Session = Depends(db_session)):
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found")
    result = paper_data(paper)
    result["batches"] = [{"batch_id": job.id, "batch_code": f"BATCH-{job.id:06d}", "dataset_id": job.dataset_id,
                          "status": job.status, "imported_at": imported_at}
                         for job, imported_at in db.execute(select(Job, PaperBatch.imported_at)
                            .join(PaperBatch, PaperBatch.job_id == Job.id).where(PaperBatch.paper_id == paper_id)
                            .order_by(Job.id))]
    result["batch_ids"] = [batch["batch_id"] for batch in result["batches"]]
    result["annotations"] = []  # B's reviewed entity extraction will extend this field.
    result["sources"] = [{"name": s.source, "source_id": s.source_id,
                           "url": s.source_url, "retrieved_at": s.retrieved_at}
                          for s in db.scalars(select(PaperSource).where(PaperSource.paper_id == paper_id)
                                              .order_by(PaperSource.id))]
    return result


@app.get("/api/papers/{paper_id}/graph")
def get_paper_graph(paper_id: int, db: Session = Depends(db_session)):
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found")
    paper_node = f"paper:{paper.id}"
    venue_node = f"venue:{paper.venue}"
    return {"basis": "paper_metadata", "nodes": [
        {"id": paper_node, "type": "Paper", "label": paper.title, "paper_id": paper.id},
        {"id": venue_node, "type": "Venue", "label": paper.venue}],
        "edges": [{"source": paper_node, "target": venue_node, "type": "PUBLISHED_IN"}]}


@app.get("/api/admin/export", dependencies=[Depends(admin)])
def export_papers(venue: str | None = None, year: int | None = Query(default=None, ge=1980, le=2100),
                  batch_id: int | None = Query(default=None, ge=1),
                  db: Session = Depends(db_session)):
    conditions = paper_filter(venue, year, batch_id=batch_id)
    count = db.scalar(select(func.count(Paper.id)).where(*conditions))
    if count > 10000:
        raise HTTPException(422, "Select a venue/year to export at most 10000 papers")
    output = io.StringIO(newline="")
    fields = ["paper_id", "canonical_key", "openalex_id", "doi", "title", "authors_json", "abstract", "venue", "year", "source_url", "batch_ids_json"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    papers = db.scalars(select(Paper).where(*conditions).order_by(Paper.id)).all()
    batches = batch_map(db, [paper.id for paper in papers])
    for paper in papers:
        writer.writerow({"paper_id": paper.id, "canonical_key": paper.canonical_key,
                         "openalex_id": paper.openalex_id, "doi": paper.doi, "title": paper.title,
                         "authors_json": paper.authors_json, "abstract": paper.abstract,
                         "venue": paper.venue, "year": paper.year, "source_url": paper.source_url,
                         "batch_ids_json": json.dumps(batches.get(paper.id, []))})
    return Response(content="\ufeff" + output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="papers.csv"', "X-Paper-Count": str(count)})


@app.get("/api/admin/datasets", dependencies=[Depends(admin)])
def list_datasets():
    manifest, _ = load_sample()
    return {"items": [manifest]}


@app.get("/api/import-overview")
def import_overview(db: Session = Depends(db_session)):
    """Read-only import results; credentials and administrative logs remain protected."""
    manifest, _ = load_sample()
    jobs = db.scalars(select(Job).order_by(Job.id.desc()).limit(100)).all()
    counts = dict(db.execute(select(PaperBatch.job_id, func.count(PaperBatch.paper_id))
                             .group_by(PaperBatch.job_id)).all())
    batches = []
    for job in jobs:
        item = job_data(job)
        item.pop("error", None)
        item["paper_count"] = counts.get(job.id, 0)
        batches.append(item)
    return {"dataset": manifest, "total_papers": db.scalar(select(func.count(Paper.id))), "batches": batches}


@app.post("/api/admin/imports", dependencies=[Depends(admin)], status_code=201, response_model=SampleImportView)
def import_fixed_sample(payload: SampleImport, db: Session = Depends(db_session)):
    try:
        job = import_sample(db, payload.dataset_id)
    except ImportConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    result = job_data(job)
    result["paper_count"] = db.scalar(select(func.count()).select_from(PaperBatch).where(PaperBatch.job_id == job.id))
    result["total_papers"] = db.scalar(select(func.count(Paper.id)))
    return result


@app.get("/api/admin/sources", dependencies=[Depends(admin)])
def list_sources(db: Session = Depends(db_session)):
    return [{"name": x.name, "enabled": x.enabled, "page_size": x.page_size,
             "max_retries": x.max_retries, "updated_at": x.updated_at,
             "credential_configured": bool(os.getenv("OPENALEX_API_KEY")) if x.name == "openalex" else None}
            for x in db.scalars(select(Source).order_by(Source.name))]


@app.put("/api/admin/sources/{name}", dependencies=[Depends(admin)])
def update_source(name: str, payload: SourceUpdate, db: Session = Depends(db_session)):
    source = db.scalar(select(Source).where(Source.name == name))
    if not source:
        raise HTTPException(404, "Unknown source")
    source.enabled = payload.enabled
    source.page_size = payload.page_size
    source.max_retries = payload.max_retries
    source.updated_at = now()
    db.commit()
    return {"name": source.name, "enabled": source.enabled, "page_size": source.page_size, "max_retries": source.max_retries}


@app.post("/api/admin/jobs", dependencies=[Depends(admin)], status_code=201, response_model=JobView)
def create_job(payload: JobCreate, db: Session = Depends(db_session)):
    venue = payload.venue.upper()
    if venue not in VENUES:
        raise HTTPException(422, "Supported venues: CVPR, ICCV, ECCV")
    if payload.year > datetime.utcnow().year:
        raise HTTPException(422, "Year cannot be in the future")
    dblp = db.scalar(select(Source).where(Source.name == "dblp"))
    openalex = db.scalar(select(Source).where(Source.name == "openalex"))
    if payload.source == "openalex" and venue not in OPENALEX_SOURCES:
        raise HTTPException(422, f"OpenAlex conference source is not configured for {venue}")
    if payload.source == "dblp" and (not dblp or not dblp.enabled):
        raise HTTPException(409, "DBLP source is disabled")
    if payload.source == "openalex" and (not openalex or not openalex.enabled):
        raise HTTPException(409, "OpenAlex source is disabled")
    if payload.source == "auto" and not ((dblp and dblp.enabled) or (openalex and openalex.enabled and venue in OPENALEX_SOURCES)):
        raise HTTPException(409, "No enabled source is available for this venue")
    active = db.scalar(select(Job).where(Job.venue == venue, Job.year == payload.year, Job.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(409, f"Job {active.id} is already active for this venue/year")
    job = Job(venue=venue, year=payload.year, source=payload.source, active_key=f"{venue}:{payload.year}")
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A job is already active for this venue/year")
    return job_data(job)


@app.get("/api/admin/jobs", dependencies=[Depends(admin)], response_model=list[JobView])
def list_jobs(db: Session = Depends(db_session)):
    return [job_data(x) for x in db.scalars(select(Job).order_by(Job.id.desc()).limit(100))]


@app.get("/api/admin/jobs/{job_id}", dependencies=[Depends(admin)])
def get_job(job_id: int, db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    result = job_data(job)
    result["paper_count"] = db.scalar(select(func.count()).select_from(PaperBatch).where(PaperBatch.job_id == job_id))
    result["events"] = [{"stage": e.stage, "level": e.level, "message": e.message, "created_at": e.created_at}
                        for e in db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id.desc()).limit(100))]
    return result


@app.get("/api/admin/jobs/{job_id}/papers", dependencies=[Depends(admin)])
def get_batch_papers(job_id: int, page: int = Query(default=1, ge=1),
                     page_size: int = Query(default=20, ge=1, le=100), db: Session = Depends(db_session)):
    if db.get(Job, job_id) is None:
        raise HTTPException(404, "Batch not found")
    result = list_papers(q=None, venue=None, year=None, page=page, page_size=page_size, batch_id=job_id, db=db)
    result["batch_id"] = job_id
    return result


@app.post("/api/admin/jobs/{job_id}/retry", dependencies=[Depends(admin)])
def retry_job(job_id: int, db: Session = Depends(db_session)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("failed", "partial"):
        raise HTTPException(409, "Only failed or partial jobs can be retried")
    if job.source == "ecva":
        raise HTTPException(409, "ECVA batches must be retried through the import command")
    if job.kind == "sample":
        try:
            return job_data(import_sample(db, job.dataset_id, job=job))
        except ImportConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
    active = db.scalar(select(Job).where(Job.venue == job.venue, Job.year == job.year,
                                         Job.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(409, f"Job {active.id} is already active")
    job.status = "queued"
    job.active_key = f"{job.venue}:{job.year}"
    job.stage = "queued"
    job.attempted = job.succeeded = job.failed = 0
    job.error = None
    job.started_at = job.finished_at = None
    job.updated_at = now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A job is already active for this venue/year")
    return job_data(job)
