"""Import an ECVA conference batch into MySQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from .db import SessionLocal, seed_sources
from .ingest import log, upsert_paper
from .models import Job, Source, now


def import_batch(path: Path) -> dict:
    from .batch_import import import_file
    seed_sources()
    from .worker_lock import worker_lock
    with worker_lock(SessionLocal), SessionLocal() as db:
        return import_file(db, path, "ECCV", 2024, "ecva")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(import_batch(args.path), ensure_ascii=False))
