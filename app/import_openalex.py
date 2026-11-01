"""Import a checked OpenAlex JSONL batch into MySQL with provenance and job logging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .ingest import log, openalex_work_row, upsert_paper
from .models import Job, Source, now


work_row = openalex_work_row


def import_batch(venue: str, year: int, path: Path) -> dict:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if manifest["venue"] != venue or manifest["year"] != year or manifest["source"] != "openalex":
        raise ValueError("Batch manifest does not match venue/year/source")
    with SessionLocal() as db:
        source = db.scalar(select(Source).where(Source.name == "openalex"))
        if not source or not source.enabled:
            raise ValueError("OpenAlex source is disabled")
        job = Job(venue=venue, year=year, source="openalex", kind="file", status="running", stage="import", started_at=now())
        db.add(job)
        db.commit()
        try:
            with path.open(encoding="utf-8") as file:
                for line in file:
                    job.attempted += 1
                    try:
                        work = json.loads(line)
                        location = work.get("primary_location") or {}
                        actual_source = (location.get("source") or {}).get("id", "")
                        if not actual_source.endswith(manifest["source_id"]):
                            raise ValueError("Work source does not match manifest")
                        row = work_row(work, venue, year)
                        with db.begin_nested():
                            upsert_paper(db, row, "openalex", job=job)
                        job.succeeded += 1
                        db.commit()
                    except Exception as exc:
                        job.failed += 1
                        log(db, job, "import", "error", f"Line {job.attempted}: {type(exc).__name__}: {str(exc)[:300]}")
                    if job.succeeded and job.succeeded % source.page_size == 0:
                        log(db, job, "import", "info", f"Processed {job.succeeded}/{manifest['count']}")
            if job.attempted != manifest["count"]:
                raise ValueError(f"Batch length {job.attempted} differs from manifest count {manifest['count']}")
            job.status = "partial" if job.failed else "succeeded"
            job.finished_at = now()
            log(db, job, "done", "info", f"Imported {job.succeeded}/{job.attempted}; {job.failed} failed")
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            job.finished_at = now()
            log(db, job, "failed", "error", job.error)
            raise
        return {"id": job.id, "venue": venue, "year": year, "status": job.status,
                "attempted": job.attempted, "succeeded": job.succeeded, "failed": job.failed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("venue", choices=("CVPR", "ICCV", "ECCV"))
    parser.add_argument("year", type=int)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_batch(args.venue, args.year, args.path), ensure_ascii=False))
