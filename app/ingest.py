from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Job, JobEvent, Paper, PaperBatch, PaperSource, Source, now
from .paths import configured_path
from scripts.fetch_openalex_batch import SOURCES as OPENALEX_SOURCES

VENUES = {"CVPR": "cvpr", "ICCV": "iccv", "ECCV": "eccv"}
TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))


def clean_title(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", value)).strip().rstrip(".")


def normalize_title(value: str) -> str:
    return re.sub(r"[^\w]+", " ", clean_title(value).casefold()).strip()


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", value.strip(), flags=re.I).lower()
    return value or None


def decode_abstract(index: dict | None) -> str | None:
    if not index:
        return None
    positions = {int(position): word for word, numbers in index.items() for position in numbers}
    return " ".join(positions.get(i, "") for i in range(max(positions) + 1)).strip() if positions else None


def openalex_work_row(work: dict, venue: str, year: int) -> dict:
    title = clean_title(work.get("display_name") or "")
    if not title or work.get("publication_year") != year:
        raise ValueError("Missing title or wrong publication year")
    identifier = work["id"]
    return {
        "source_id": identifier,
        "source_url": identifier,
        "title": title,
        "year": year,
        "venue": venue,
        "doi": normalize_doi(work.get("doi")),
        "authors": [a["author"]["display_name"] for a in work.get("authorships", [])
                    if a.get("author", {}).get("display_name")],
        "abstract": decode_abstract(work.get("abstract_inverted_index")),
        "cited_by_count": work.get("cited_by_count"),
        "raw": work,
    }


def parse_dblp_xml(body: bytes, venue: str, year: int) -> list[dict]:
    if not body.lstrip().startswith(b"<?xml") and not body.lstrip().startswith(b"<dblp"):
        raise ValueError("DBLP did not return XML; check upstream access or venue/year")
    root = ET.fromstring(body)
    if root.tag != "dblp":
        raise ValueError("Unexpected DBLP XML root")
    papers = []
    for item in root:
        if item.tag != "inproceedings":
            continue
        key = item.get("key", "")
        if not key.startswith(f"conf/{VENUES[venue]}/"):
            continue
        item_year = item.findtext("year")
        if item_year != str(year):
            continue
        title_node = item.find("title")
        title = clean_title("".join(title_node.itertext())) if title_node is not None else ""
        if not title:
            continue
        ee = item.findtext("ee")
        doi = normalize_doi(item.findtext("ee") if ee and "doi.org/" in ee else None)
        record = {
            "source_id": key,
            "title": title,
            "year": year,
            "venue": venue,
            "dblp_key": key,
            "doi": doi,
            "authors": ["".join(a.itertext()).strip() for a in item.findall("author")],
            "source_url": f"https://dblp.org/rec/{key}",
            "ee": ee,
        }
        record["raw"] = {"dblp_xml": ET.tostring(item, encoding="unicode"), "parsed": record.copy()}
        papers.append(record)
    return papers


def fetch_dblp(venue: str, year: int, session: requests.Session, retries: int = 3) -> list[dict]:
    slug = VENUES[venue]
    url = f"https://dblp.org/db/conf/{slug}/{slug}{year}.xml"
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=TIMEOUT, headers={"User-Agent": "tupu-research-ingest/0.1 (metadata only)"})
            response.raise_for_status()
            return parse_dblp_xml(response.content, venue, year)
        except (requests.RequestException, ValueError, ET.ParseError):
            if attempt + 1 == retries:
                raise
            time.sleep(min(2 ** attempt, 8))
    return []


def fetch_openalex(doi: str, session: requests.Session, retries: int = 3) -> dict | None:
    url = "https://api.openalex.org/works/https://doi.org/" + quote(doi, safe="/")
    params = {}
    if os.getenv("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=TIMEOUT)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return {
                "source_id": data["id"],
                "source_url": data["id"],
                "doi": normalize_doi(data.get("doi")),
                "abstract": decode_abstract(data.get("abstract_inverted_index")),
                "cited_by_count": data.get("cited_by_count"),
                "authors": [a.get("author", {}).get("display_name") for a in data.get("authorships", [])],
                "raw": data,
            }
        except (requests.RequestException, ValueError, KeyError):
            if attempt + 1 == retries:
                raise
            time.sleep(min(2 ** attempt, 8))
    return None


def upsert_paper(db: Session, row: dict, source: str = "dblp", paper: Paper | None = None, job: Job | None = None) -> Paper:
    doi = normalize_doi(row.get("doi"))
    source_id = row["source_id"]
    existing_source = db.scalar(select(PaperSource).where(PaperSource.source == source, PaperSource.source_id == source_id))
    if existing_source:
        paper = db.get(Paper, existing_source.paper_id)
    if paper is None and doi:
        paper = db.scalar(select(Paper).where(Paper.doi == doi))
    if paper is None and row.get("dblp_key"):
        paper = db.scalar(select(Paper).where(Paper.dblp_key == row["dblp_key"]))
    if paper is None and not doi and row.get("title"):
        paper = db.scalar(select(Paper).where(Paper.title_normalized == normalize_title(row["title"]), Paper.year == row["year"], Paper.venue == row["venue"]))
    if paper is None:
        key = "doi:" + doi if doi else f"{source}:" + source_id
        paper = Paper(canonical_key=key, title=row["title"], title_normalized=normalize_title(row["title"]), year=row["year"], venue=row["venue"])
        db.add(paper)
        db.flush()
    if source == "dblp":
        paper.title = row["title"]
        paper.title_normalized = normalize_title(row["title"])
        paper.year = row["year"]
        paper.venue = row["venue"]
        paper.dblp_key = row["dblp_key"]
        paper.authors_json = json.dumps(row.get("authors", []), ensure_ascii=False)
        paper.source_url = row.get("source_url")
    elif source == "openalex":
        paper.openalex_id = source_id
        if not paper.dblp_key:
            paper.title = row.get("title") or paper.title
            paper.title_normalized = normalize_title(paper.title)
            paper.authors_json = json.dumps(row.get("authors", []), ensure_ascii=False)
            paper.source_url = row.get("source_url")
        paper.abstract = row.get("abstract") or paper.abstract
        paper.cited_by_count = row.get("cited_by_count")
    else:
        paper.title = row["title"]
        paper.title_normalized = normalize_title(row["title"])
        paper.year = row["year"]
        paper.venue = row["venue"]
        paper.authors_json = json.dumps(row.get("authors", []), ensure_ascii=False)
        paper.source_url = row.get("source_url")
    paper.doi = doi or paper.doi
    paper.updated_at = now()
    if existing_source is None:
        existing_source = PaperSource(paper_id=paper.id, source=source, source_id=source_id)
        db.add(existing_source)
    existing_source.source_url = row.get("source_url")
    existing_source.retrieved_at = now()
    existing_source.raw_json = json.dumps(row.get("raw", row), ensure_ascii=False)
    if job is not None:
        if db.get(PaperBatch, (job.id, paper.id)) is None:
            db.add(PaperBatch(job_id=job.id, paper_id=paper.id))
    return paper


def log(db: Session, job: Job, stage: str, level: str, message: str) -> None:
    job.stage = stage
    job.updated_at = now()
    db.add(JobEvent(job_id=job.id, stage=stage, level=level, message=message[:2000]))
    db.commit()


def run_openalex_job(db: Session, job: Job) -> None:
    from scripts.fetch_openalex_batch import fetch_batch

    source = db.scalar(select(Source).where(Source.name == "openalex"))
    if not source or not source.enabled or job.venue not in OPENALEX_SOURCES:
        job.status = "failed"
        job.active_key = None
        job.error = f"OpenAlex is unavailable for {job.venue}"
        job.finished_at = now()
        log(db, job, "failed", "error", job.error)
        return
    job.status = "running"
    job.started_at = job.started_at or now()
    path = configured_path("BATCH_DIR", "data/raw") / f"{job.venue.lower()}_{job.year}.jsonl"
    cache_used = False
    log(db, job, "fetch", "info", f"Fetching {job.venue} {job.year} from OpenAlex")
    try:
        try:
            manifest = fetch_batch(job.venue, job.year, path, retries=source.max_retries)
            log(db, job, "fetch", "info", f"Downloaded {manifest['count']} OpenAlex records")
        except Exception as exc:
            manifest_path = path.with_suffix(".manifest.json")
            if not path.exists() or not manifest_path.exists():
                raise
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (manifest.get("venue"), manifest.get("year"), manifest.get("source"), manifest.get("source_id")) != (
                job.venue, job.year, "openalex", OPENALEX_SOURCES[job.venue]
            ):
                raise ValueError("Cached OpenAlex batch does not match the requested venue/year") from exc
            cache_used = True
            log(db, job, "fetch", "warning", f"OpenAlex unavailable ({type(exc).__name__}); using cached batch")
        if not isinstance(manifest.get("count"), int) or manifest["count"] <= 0:
            raise ValueError("OpenAlex batch has no valid record count")
        with path.open(encoding="utf-8") as file:
            for line in file:
                job.attempted += 1
                try:
                    work = json.loads(line)
                    location = work.get("primary_location") or {}
                    actual_source = (location.get("source") or {}).get("id", "")
                    if work.get("publication_year") != job.year or not actual_source.endswith(OPENALEX_SOURCES[job.venue]):
                        raise ValueError("Work venue/year does not match batch")
                    row = openalex_work_row(work, job.venue, job.year)
                    with db.begin_nested():
                        upsert_paper(db, row, "openalex", job=job)
                    job.succeeded += 1
                    db.commit()
                except Exception as exc:
                    job.failed += 1
                    log(db, job, "upsert", "error", f"Line {job.attempted}: {type(exc).__name__}: {str(exc)[:300]}")
                if job.attempted % source.page_size == 0:
                    log(db, job, "upsert", "info", f"Processed {job.attempted}/{manifest['count']}")
        if job.attempted != manifest["count"]:
            raise ValueError(f"Batch length {job.attempted} differs from expected {manifest['count']}")
        job.status = "partial" if job.failed or cache_used else "succeeded"
        if cache_used:
            job.error = "Upstream unavailable; cached records were imported. Retry to refresh from OpenAlex."
        job.active_key = None
        job.finished_at = now()
        log(db, job, "done", "info", f"Completed: {job.succeeded} succeeded, {job.failed} failed")
    except Exception as exc:
        job.status = "failed"
        job.active_key = None
        job.error = f"{type(exc).__name__}: {str(exc)[:300]}" if not isinstance(exc, requests.RequestException) else f"{type(exc).__name__}: upstream OpenAlex request failed"
        job.finished_at = now()
        log(db, job, "failed", "error", job.error)


def run_job(db: Session, job: Job, http: requests.Session | None = None) -> None:
    if job.kind == "sample":
        from .datasets import import_sample
        try:
            import_sample(db, job.dataset_id, job=job)
        except Exception as exc:
            job.status = "failed"
            job.active_key = None
            job.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            job.finished_at = now()
            log(db, job, "failed", "error", job.error)
        return
    http = http or requests.Session()
    if job.source == "openalex":
        run_openalex_job(db, job)
        return
    source = db.scalar(select(Source).where(Source.name == "dblp"))
    if not source or not source.enabled:
        if job.source == "auto":
            run_openalex_job(db, job)
            return
        job.status = "failed"
        job.active_key = None
        job.error = "DBLP source is disabled"
        job.finished_at = now()
        log(db, job, "fetch", "error", job.error)
        return
    job.status = "running"
    job.started_at = now()
    log(db, job, "fetch", "info", f"Fetching {job.venue} {job.year} from DBLP")
    try:
        try:
            rows = fetch_dblp(job.venue, job.year, http, source.max_retries)
            if not rows:
                raise ValueError("DBLP returned no conference papers; verify venue/year before retrying")
        except Exception as exc:
            openalex = db.scalar(select(Source).where(Source.name == "openalex"))
            if job.source == "auto" and job.venue in OPENALEX_SOURCES and openalex and openalex.enabled:
                log(db, job, "fetch", "warning", f"DBLP unavailable ({type(exc).__name__}); trying OpenAlex")
                run_openalex_job(db, job)
                return
            raise
        job.attempted = len(rows)
        log(db, job, "upsert", "info", f"Fetched {len(rows)} DBLP records")
        for row in rows:
            try:
                with db.begin_nested():
                    paper = upsert_paper(db, row, job=job)
                    db.flush()
                job.succeeded += 1
                db.commit()
            except Exception as exc:
                job.failed += 1
                log(db, job, "upsert", "error", f"{row['source_id']}: {type(exc).__name__}: {str(exc)[:300]}")
                continue
            oa_source = db.scalar(select(Source).where(Source.name == "openalex"))
            if row.get("doi") and oa_source and oa_source.enabled:
                try:
                    enriched = fetch_openalex(row["doi"], http, oa_source.max_retries)
                    if enriched:
                        with db.begin_nested():
                            upsert_paper(db, enriched, "openalex", paper)
                        db.commit()
                except Exception as exc:
                    # HTTP errors can include the request URL and its API key.
                    log(db, job, "enrich", "warning", f"{row['source_id']}: OpenAlex {type(exc).__name__}")
            if job.succeeded % source.page_size == 0:
                log(db, job, "enrich", "info", f"Processed {job.succeeded}/{job.attempted}")
        job.status = "partial" if job.failed else "succeeded"
        job.active_key = None
        job.finished_at = now()
        log(db, job, "done", "info", f"Completed: {job.succeeded} succeeded, {job.failed} failed")
    except Exception as exc:
        job.status = "failed"
        job.active_key = None
        job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        job.finished_at = now()
        log(db, job, "failed", "error", job.error)
