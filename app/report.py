from __future__ import annotations

import argparse
import json
from sqlalchemy import select

from .db import SessionLocal
from .ingest import VENUES
from .models import Job, Paper, PaperBatch, PaperSource
from .paper_quality import research_paper_scope


def batch_quality(db, job: Job, expected: int | None = None) -> dict:
    from .pipeline import record_counts
    papers = db.scalars(select(Paper).join(PaperBatch, PaperBatch.paper_id == Paper.id)
                        .where(PaperBatch.job_id == job.id, research_paper_scope())).all()
    ids = [paper.id for paper in papers]
    sourced = set(db.scalars(select(PaperSource.paper_id).where(PaperSource.paper_id.in_(ids))))
    count = len(papers)
    sample = job.kind == "sample"
    if sample:
        from .datasets import load_sample
        from .additional_samples import DATASETS
        if job.dataset_id in DATASETS:
            expected = 20
        else:
            manifest, _ = load_sample(job.dataset_id)
            expected = manifest['expected_count']
    missing = {"doi": [p.id for p in papers if not p.doi],
               "abstract": [p.id for p in papers if not p.abstract or not p.abstract.strip()],
               "authors": [p.id for p in papers if not json.loads(p.authors_json)],
               "provenance": [p.id for p in papers if p.id not in sourced]}
    return {"batch_id": job.id, "dataset_id": job.dataset_id, "papers": count,
            "scope": "fixed_sample" if sample else "conference_year",
            "expected_papers": expected,
            "coverage_basis": "fixed_sample_manifest" if sample else "caller_supplied" if expected else None,
            "coverage_ratio": round(count / expected, 4) if expected else None,
            "missing": missing, "records": record_counts(db, job.id),
            "status": job.status}


def build_report(venue: str, year: int, expected: int | None = None) -> dict:
    with SessionLocal() as db:
        papers = db.scalars(select(Paper).where(Paper.venue == venue, Paper.year == year, research_paper_scope())).all()
        jobs = db.scalars(select(Job).where(Job.venue == venue, Job.year == year).order_by(Job.id.desc()).limit(5)).all()
    count = len(papers)
    return {
        "venue": venue,
        "year": year,
        "papers": count,
        "with_doi": sum(p.doi is not None for p in papers),
        "with_abstract": sum(bool((p.abstract or "").strip()) for p in papers),
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
