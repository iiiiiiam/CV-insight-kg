"""Import an ECVA conference batch into MySQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal
from .ingest import log, upsert_paper
from .models import Job, Source, now


def import_batch(path: Path) -> dict:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if (manifest["venue"], manifest["year"], manifest["source"]) != ("ECCV", 2024, "ecva"):
        raise ValueError("Unexpected ECVA batch manifest")
    with SessionLocal() as db:
        source = db.scalar(select(Source).where(Source.name == "ecva"))
        if source is None:
            source = Source(name="ecva")
            db.add(source)
            db.commit()
        if not source.enabled:
            raise ValueError("ECVA source is disabled")
        job = Job(venue="ECCV", year=2024, source="ecva", kind="file", status="running", stage="import", started_at=now())
        db.add(job)
        db.commit()
        try:
            with path.open(encoding="utf-8") as file:
                for line in file:
                    job.attempted += 1
                    try:
                        row = json.loads(line)
                        if row["venue"] != "ECCV" or row["year"] != 2024:
                            raise ValueError("Wrong venue/year in row")
                        with db.begin_nested():
                            upsert_paper(db, row, "ecva", job=job)
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
        return {"id": job.id, "status": job.status, "attempted": job.attempted,
                "succeeded": job.succeeded, "failed": job.failed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_batch(args.path), ensure_ascii=False))
