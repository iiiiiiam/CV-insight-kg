"""The fixed week-one dataset and its repeatable, audited import operation."""

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ingest import log, openalex_work_row, upsert_paper
from .models import Job, Source, now
from .paths import configured_path

DATASET_ID = "week1-cvpr2024-detection-v1"


class ImportConflict(ValueError):
    pass


def sample_directory() -> Path:
    return configured_path("SAMPLE_DIR", "examples")


def load_sample(dataset_id: str = DATASET_ID) -> tuple[dict, list[dict]]:
    if dataset_id != DATASET_ID:
        raise ValueError("Unknown sample dataset")
    directory = sample_directory()
    manifest = json.loads((directory / "week1_baseline.json").read_text(encoding="utf-8"))
    if (manifest.get("dataset_id"), manifest.get("venue"), manifest.get("year"), manifest.get("source")) != (
        DATASET_ID, "CVPR", 2024, "openalex"
    ):
        raise ValueError("Invalid baseline manifest")
    body = (directory / "cvpr_2024_seed.jsonl").read_bytes()
    if hashlib.sha256(body).hexdigest() != manifest.get("sha256"):
        raise ValueError("Sample checksum differs from the fixed baseline")
    works = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if len(works) != manifest.get("expected_count") or not 20 <= len(works) <= 30:
        raise ValueError("The week-one sample must contain the baseline's 20–30 papers")
    baseline = {paper["openalex_id"]: paper for paper in manifest["papers"]}
    if len(baseline) != len(works) or len({work["id"] for work in works}) != len(works):
        raise ValueError("Duplicate or missing baseline IDs")
    for work in works:
        row = openalex_work_row(work, manifest["venue"], manifest["year"])
        expected = baseline.get(work["id"])
        source = ((work.get("primary_location") or {}).get("source") or {}).get("id")
        if (not expected or source != "https://openalex.org/" + manifest["source_id"]
                or expected["title"] != work["display_name"] or expected["year"] != work["publication_year"]
                or expected.get("doi") != work.get("doi") or not row["source_url"]):
            raise ValueError("Sample paper differs from its baseline record")
    return manifest, works


def import_sample(db: Session, dataset_id: str = DATASET_ID, job: Job | None = None) -> Job:
    manifest, works = load_sample(dataset_id)
    source = db.scalar(select(Source).where(Source.name == "openalex"))
    if source is None or not source.enabled:
        raise ImportConflict("OpenAlex source is disabled")
    active = select(Job).where(Job.venue == manifest["venue"], Job.year == manifest["year"],
                               Job.status.in_(["queued", "running"]))
    if job is not None:
        active = active.where(Job.id != job.id)
    if db.scalar(active) is not None:
        raise ImportConflict("Another import or refresh is active for this venue/year")
    if job is None:
        job = Job(venue=manifest["venue"], year=manifest["year"], source="openalex", kind="sample", dataset_id=dataset_id)
        db.add(job)
    job.status = "running"
    job.stage = "import"
    job.active_key = f"{job.venue}:{job.year}"
    job.attempted = job.succeeded = job.failed = 0
    job.error = None
    job.started_at = now()
    job.finished_at = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ImportConflict("Another import or refresh is active for this venue/year") from exc
    log(db, job, "import", "info", f"Importing fixed dataset {dataset_id}; {len(works)} papers; SHA256 {manifest['sha256']}")
    for work in works:
        job.attempted += 1
        try:
            row = openalex_work_row(work, job.venue, job.year)
            with db.begin_nested():
                upsert_paper(db, row, "openalex", job=job)
            job.succeeded += 1
            db.commit()
        except Exception as exc:
            job.failed += 1
            log(db, job, "import", "error", f"{work['id']}: {type(exc).__name__}: {str(exc)[:300]}")
    job.status = "partial" if job.failed else "succeeded"
    job.active_key = None
    job.finished_at = now()
    log(db, job, "done", "info", f"Fixed sample completed: {job.succeeded} succeeded, {job.failed} failed")
    return job
