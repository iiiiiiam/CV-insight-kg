from __future__ import annotations

import time

from sqlalchemy import select, update

from .db import SessionLocal, seed_sources
from .ingest import run_job
from .models import Job, JobEvent, now


def claim_job() -> int | None:
    with SessionLocal() as db:
        job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.id))
        if job is None:
            return None
        result = db.execute(update(Job).where(Job.id == job.id, Job.status == "queued")
                            .values(status="running", stage="fetch", updated_at=now()))
        db.commit()
        return job.id if result.rowcount else None


def recover_jobs():
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status == "running", Job.active_key.is_not(None))):
            job.status = "queued"
            job.stage = "queued"
            job.attempted = job.succeeded = job.failed = 0
            job.error = None
            job.started_at = job.finished_at = None
            job.updated_at = now()
            db.add(JobEvent(job_id=job.id, stage="queued", level="warning",
                            message="Worker restarted; retrying the interrupted batch with reset counters"))
        db.commit()


def main():
    seed_sources()
    recover_jobs()
    while True:
        job_id = claim_job()
        if job_id is None:
            time.sleep(2)
            continue
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            run_job(db, job)


if __name__ == "__main__":
    main()
