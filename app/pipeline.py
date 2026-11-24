"""Durable refresh snapshots: commit data and its checkpoint together."""
from __future__ import annotations

import json
import os
import re

from sqlalchemy import func, select

from .models import JobEvent, JobRecord, Source, now
from .paper_quality import is_front_matter


def safe_error(exc: Exception) -> str:
    message = str(exc)
    # Requests exceptions can contain credential-bearing URLs.
    message = re.sub(r"https?://\S+", "[upstream URL]", message)
    for name in ("OPENALEX_API_KEY", "ADMIN_TOKEN", "A_ADMIN_TOKEN", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return f"{type(exc).__name__}: {message[:400]}"


def has_snapshot(db, job) -> bool:
    return db.scalar(select(JobRecord.id).where(JobRecord.job_id == job.id).limit(1)) is not None


def save_snapshot(db, job, rows, source):
    """All inputs are committed before processing any paper."""
    seen = set()
    for row in rows:
        identifier = row["source_id"]
        if not identifier or identifier in seen:
            raise ValueError("Missing or duplicate source ID in refresh snapshot")
        seen.add(identifier)
        db.add(JobRecord(job_id=job.id, source=source, source_id=identifier,
                         payload_json=json.dumps(row, ensure_ascii=False)))
    if not seen:
        raise ValueError("Refresh snapshot is empty")
    db.commit()


def record_counts(db, job_id):
    counts = dict(db.execute(select(JobRecord.status, func.count(JobRecord.id))
                            .where(JobRecord.job_id == job_id).group_by(JobRecord.status)).all())
    return {"total": sum(counts.values()), "pending": counts.get("pending", 0),
            "succeeded": counts.get("succeeded", 0), "failed": counts.get("failed", 0), "skipped": counts.get("skipped", 0)}


def process_snapshot(db, job, http=None, warning=None, enrich=True):
    from .ingest import fetch_openalex, log, openalex_work_row, upsert_paper
    if http is None:
        import requests
        http = requests.Session()

    for name in db.scalars(select(JobRecord.source).where(JobRecord.job_id == job.id).distinct()):
        configured = db.scalar(select(Source).where(Source.name == name))
        if not configured or not configured.enabled:
            raise ValueError(f'{name} source is disabled')
    job.status = "running"
    job.started_at = job.started_at or now()
    job.finished_at = None
    job.error = None
    log(db, job, "upsert", "info", "Processing saved snapshot; successful records are skipped")
    records = db.scalars(select(JobRecord).where(JobRecord.job_id == job.id,
                                                JobRecord.status.not_in(("succeeded", "skipped"))).order_by(JobRecord.id)).all()
    counts = record_counts(db, job.id)
    for record in records:
        previous_status = record.status
        record.attempts += 1
        try:
            row = json.loads(record.payload_json)
            if row.get("openalex_work"):
                cached = row.get("_cached", False)
                row = dict(openalex_work_row(row["raw"], job.venue, job.year), _cached=cached)
            if is_front_matter(row):
                record.status = 'skipped'
                record.stage = 'done'
                record.error = '目录、版权页或会议组织信息，非研究论文'
                counts[previous_status] -= 1
                counts['skipped'] += 1
                job.succeeded, job.failed, job.skipped = counts['succeeded'], counts['failed'], counts['skipped']
                job.attempted = job.succeeded + job.failed + job.skipped
                db.commit()
                continue
            if record.source == "cvf" and row.get("include_detail"):
                from .cvf import fetch_detail
                row = fetch_detail(row, http)
            work = None
            if record.source == 'ecva' and not row.get('skip_network'):
                from .ecva import fetch_detail, match_openalex
                if not row.get('_detail_complete'):
                    from .network import retry_request
                    configured = db.scalar(select(Source).where(Source.name == 'ecva'))
                    row = retry_request(lambda: fetch_detail(row,http),configured.max_retries)
                    record.payload_json = json.dumps(row, ensure_ascii=False)
                    db.commit()
                oa = db.scalar(select(Source).where(Source.name == 'openalex', Source.enabled.is_(True)))
                if oa:
                    work = match_openalex(row, http, retries=oa.max_retries)
            # A successful paper write is never committed without its checkpoint.
            # Enrichment failure is retried separately without undoing base metadata.
            if record.stage == "upsert":
                with db.begin_nested():
                    if record.source == 'ecva':
                        from .official import save_official
                        save_official(db, row, work, job, record.source)
                    else:
                        upsert_paper(db, row, record.source, job=job)
                record.stage = "enrich" if enrich and not row.get("skip_enrichment") and record.source == "dblp" and row.get("doi") else "done"
                db.commit()
            if record.stage == "enrich":
                source = db.scalar(select(Source).where(Source.name == "openalex"))
                if source and source.enabled:
                    enriched = fetch_openalex(row["doi"], http, source.max_retries)
                    if enriched:
                        # Resolve the already imported paper by its DBLP provenance.
                        from .models import Paper, PaperSource
                        paper_id = db.scalar(select(PaperSource.paper_id).where(
                            PaperSource.source == "dblp", PaperSource.source_id == record.source_id))
                        with db.begin_nested():
                            upsert_paper(db, enriched, "openalex", db.get(Paper, paper_id), job=job)
                record.stage = "done"
            record.status = "succeeded"
            record.error = None
        except Exception as exc:
            record.status = "failed"
            record.error = safe_error(exc)
            db.add(JobEvent(job_id=job.id, stage=record.stage, level="error",
                            message=f"{record.source_id}: {record.error}"))
        record.updated_at = now()
        db.flush()
        counts[previous_status] -= 1
        counts[record.status] += 1
        job.succeeded, job.failed = counts["succeeded"], counts["failed"]
        job.skipped = counts["skipped"]
        job.attempted = job.succeeded + job.failed + job.skipped
        job.updated_at = now()
        db.commit()
    counts = record_counts(db, job.id)
    job.succeeded, job.failed = counts["succeeded"], counts["failed"]
    job.skipped = counts["skipped"]
    job.attempted = job.succeeded + job.failed + job.skipped
    job.status = "partial" if job.failed or warning else "succeeded"
    job.error = warning or (f"{job.failed} records failed; retry resumes their saved stages" if job.failed else None)
    job.active_key = None
    job.finished_at = now()
    log(db, job, "done", "info", f"Completed: {job.succeeded} succeeded, {job.failed} failed")


def saved_progress(db,job):
    counts=record_counts(db,job.id)
    if counts['total']:
        return counts
    from .models import CvfRecord
    statuses=list(db.scalars(select(CvfRecord.status).where(CvfRecord.job_id==job.id)))
    return {'total':len(statuses),'pending':statuses.count('pending'),'succeeded':statuses.count('succeeded'),'failed':statuses.count('failed'),'skipped':0}
