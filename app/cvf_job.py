"""Collect a bounded set of official CVF papers with resumable per-paper progress."""
import json
import os
import re
import requests
from sqlalchemy import select
from . import cvf
from .ingest import log, normalize_title
from .models import CvfRecord, Source, now
from scripts.fetch_openalex_batch import SOURCES
from .network import retry_request


def match_openalex(row, http):
    params = {'search': row['title'], 'filter': f"primary_location.source.id:{SOURCES[row['venue']]},publication_year:{row['year']}", 'per_page': 10}
    if os.getenv('OPENALEX_API_KEY'):
        params['api_key'] = os.environ['OPENALEX_API_KEY']
    response = http.get('https://api.openalex.org/works', params=params, timeout=30)
    response.raise_for_status()
    results = response.json()['results']
    exact = [w for w in results if normalize_title(w.get('display_name') or '') == normalize_title(row['title'])
             and w.get('publication_year') == row['year']
             and ((w.get('primary_location') or {}).get('source') or {}).get('id') == 'https://openalex.org/' + SOURCES[row['venue']]
             and re.fullmatch(r'https://openalex.org/W[0-9]+', w.get('id') or '')]
    return exact[0] if len(exact) == 1 else None


def run_cvf_job(db, job, http=None):
    http = http or requests.Session()
    job.status = 'running'
    job.started_at = job.started_at or now()
    job.error = None
    try:
        source = db.scalar(select(Source).where(Source.name == 'cvf'))
        if not source or not source.enabled:
            raise ValueError('CVF 来源不可用')
        records = db.scalars(select(CvfRecord).where(CvfRecord.job_id == job.id).order_by(CvfRecord.id)).all()
        if not records:
            log(db, job, 'fetch', 'info', '正在读取会议官方论文目录')
            _, start, count = (job.dataset_id or 'cvf:1:all').split(':')
            rows = cvf.fetch_index(job.venue, job.year, http, source.max_retries)
            selected = rows[int(start)-1:] if count == 'all' else rows[int(start)-1:int(start)-1+int(count)]
            if not selected:
                raise ValueError('起始位置超出目录范围')
            records = [CvfRecord(job_id=job.id, source_id=row['source_id'], payload=json.dumps(row, ensure_ascii=False)) for row in selected]
            db.add_all(records)
            db.commit()
        for record in records:
            if record.status == 'succeeded':
                continue
            try:
                row = json.loads(record.payload)
                if not row.get('_detail_complete'):
                    row = retry_request(lambda: cvf.fetch_detail(row,http),source.max_retries)
                    row['_detail_complete'] = True
                    record.payload = json.dumps(row, ensure_ascii=False)
                    db.commit()
                oa = db.scalar(select(Source).where(Source.name == 'openalex'))
                # Legacy direct callers without source configuration retain matching.
                work = retry_request(lambda: match_openalex(row,http),oa.max_retries if oa else 3) if oa is None or oa.enabled else None
                from .official import save_official
                with db.begin_nested():
                    save_official(db, row, work, job, 'cvf')
                    record.status = 'succeeded'
                db.commit()
                if not work:
                    log(db, job, 'match', 'warning', f"未找到唯一 OpenAlex 对应记录：{row['title']}；暂不纳入交接导出")
            except Exception as exc:
                db.rollback()
                record = db.get(CvfRecord, record.id)
                record.status = 'failed'
                db.commit()
                from .pipeline import safe_error
                message = safe_error(exc)
                log(db, job, 'process', 'error', f'{record.source_id}: {message}')
            statuses = db.scalars(select(CvfRecord.status).where(CvfRecord.job_id == job.id)).all()
            job.succeeded = statuses.count('succeeded')
            job.failed = statuses.count('failed')
            job.attempted = job.succeeded + job.failed
            db.commit()
        statuses = db.scalars(select(CvfRecord.status).where(CvfRecord.job_id == job.id)).all()
        job.succeeded = statuses.count('succeeded')
        job.failed = statuses.count('failed')
        job.attempted = job.succeeded + job.failed
        job.status = 'partial' if job.failed else 'succeeded'
        job.active_key = None
        job.finished_at = now()
        log(db, job, 'done', 'info', f'采集完成：成功 {job.succeeded}，失败 {job.failed}')
    except Exception as exc:
        db.rollback()
        job.status = 'failed'
        job.active_key = None
        job.finished_at = now()
        from .pipeline import safe_error
        job.error = safe_error(exc)
        log(db, job, 'failed', 'error', job.error)
