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
            from .pipeline import has_snapshot, record_counts
            from .models import CvfRecord
            if has_snapshot(db, job):
                counts = record_counts(db, job.id)
                job.succeeded, job.failed, job.skipped = counts['succeeded'], counts['failed'], counts['skipped']
                job.attempted = job.succeeded + job.failed + job.skipped
            else:
                statuses = list(db.scalars(select(CvfRecord.status).where(CvfRecord.job_id == job.id)))
                job.succeeded, job.failed = statuses.count('succeeded'), statuses.count('failed')
                job.skipped = 0
                job.attempted = job.succeeded + job.failed
            job.error = None
            job.finished_at = None
            job.updated_at = now()
            db.add(JobEvent(job_id=job.id, stage="queued", level="warning",
                            message="Worker restarted; resuming saved records and preserving committed progress"))
        db.commit()


def main():
    from .worker_lock import worker_lock
    with worker_lock(SessionLocal) as check_owner:
        work(check_owner)


def work(check_owner=None):
    seed_sources()
    recover_jobs()
    while True:
        if check_owner:
            check_owner()
        job_id = claim_job()
        if job_id is None:
            time.sleep(2)
            continue
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            try:
                run_job(db, job)
            except Exception as exc:
                from .pipeline import safe_error
                db.rollback()
                job = db.get(Job, job_id)
                if job:
                    job.status = 'failed'; job.active_key = None; job.finished_at = now()
                    job.error = safe_error(exc)
                    db.add(JobEvent(job_id=job_id,stage='failed',level='error',message=job.error))
                    db.commit()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
