"""Import a checked OpenAlex JSONL batch into MySQL with provenance and job logging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal, seed_sources
from .ingest import log, openalex_work_row, upsert_paper
from .models import Job, Source, now


work_row = openalex_work_row


def import_batch(venue: str, year: int, path: Path) -> dict:
    from .batch_import import import_file
    seed_sources()
    from .worker_lock import worker_lock
    with worker_lock(SessionLocal), SessionLocal() as db:
        return import_file(db, path, venue, year, "openalex")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("venue", choices=("CVPR", "ICCV", "ECCV"))
    parser.add_argument("year", type=int)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_batch(args.venue, args.year, args.path), ensure_ascii=False))
