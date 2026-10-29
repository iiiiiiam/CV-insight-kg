from __future__ import annotations

import argparse
import json
from sqlalchemy import select

from .db import SessionLocal
from .ingest import VENUES
from .models import Job, Paper


def build_report(venue: str, year: int, expected: int | None = None) -> dict:
    with SessionLocal() as db:
        papers = db.scalars(select(Paper).where(Paper.venue == venue, Paper.year == year)).all()
        jobs = db.scalars(select(Job).where(Job.venue == venue, Job.year == year).order_by(Job.id.desc()).limit(5)).all()
    count = len(papers)
    return {
        "venue": venue,
        "year": year,
        "papers": count,
        "with_doi": sum(p.doi is not None for p in papers),
        "with_abstract": sum(p.abstract is not None for p in papers),
        "with_openalex_id": sum(p.openalex_id is not None for p in papers),
        "expected_papers": expected,
        "coverage_ratio": round(count / expected, 4) if expected else None,
        "recent_jobs": [{"id": j.id, "status": j.status, "attempted": j.attempted,
                         "succeeded": j.succeeded, "failed": j.failed} for j in jobs],
    }


def main():
    parser = argparse.ArgumentParser(description="Conference/year ingestion quality report")
    parser.add_argument("venue", choices=VENUES)
    parser.add_argument("year", type=int)
    parser.add_argument("--expected", type=int, help="independently verified baseline count")
    args = parser.parse_args()
    if args.expected is not None and args.expected <= 0:
        parser.error("--expected must be positive")
    print(json.dumps(build_report(args.venue, args.year, args.expected), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
