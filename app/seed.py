"""Load the bundled real metadata sample without making network requests."""

import argparse
import json
from pathlib import Path

from .db import SessionLocal, seed_sources
from .datasets import DATASET_ID, import_sample
from .import_openalex import import_batch


def seed(path: Path | None = None) -> dict:
    seed_sources()
    if path is not None:
        return import_batch("CVPR", 2024, path)
    with SessionLocal() as db:
        job = import_sample(db, DATASET_ID)
        return {"id": job.id, "batch_id": job.id, "dataset_id": job.dataset_id,
                "venue": job.venue, "year": job.year, "status": job.status,
                "attempted": job.attempted, "succeeded": job.succeeded, "failed": job.failed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path)
    args = parser.parse_args()
    result = seed(args.path)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "succeeded":
        raise SystemExit(1)
