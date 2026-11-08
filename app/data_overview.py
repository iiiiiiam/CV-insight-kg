"""Data-management statistics and a provenance-preserving B handoff."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Job, Paper, PaperBatch, PaperSource, now
from .paper_quality import research_paper_scope
from .paper_links import paper_homepage


def batch_summary(db: Session, job: Job) -> dict:
    count = db.scalar(select(func.count(PaperBatch.paper_id)).where(PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())))) or 0
    unknown = db.scalar(select(func.count(PaperBatch.paper_id)).where(
        PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())), PaperBatch.is_new.is_(None))) or 0
    new = None if unknown else (db.scalar(select(func.count(PaperBatch.paper_id)).where(
        PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())), PaperBatch.is_new.is_(True))) or 0)
    return {'id': job.id, 'batch_code': f'BATCH-{job.id:06d}', 'dataset_id': job.dataset_id,
            'venue': job.venue, 'year': job.year, 'source': job.source, 'status': job.status,
            'stage': job.stage, 'attempted': job.attempted, 'succeeded': job.succeeded,
            'failed': job.failed, 'paper_count': count, 'new_papers': new,
            'duplicate_papers': None if new is None else max(0, job.succeeded-new), 'kind': job.kind,
            'created_at': job.created_at, 'started_at': job.started_at, 'finished_at': job.finished_at}


def dashboard(db: Session, days: int = 7) -> dict:
    today = now().date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min)
    end = datetime.combine(today + timedelta(days=1), time.min)
    papers = db.scalars(select(Paper).where(research_paper_scope()).order_by(Paper.first_seen_at.desc(), Paper.id.desc())).all()
    paper_map = {p.id: p for p in papers}
    by_day = Counter(p.first_seen_at.date() for p in papers if start <= p.first_seen_at < end)
    source_records = db.execute(select(PaperSource.paper_id, PaperSource.source).where(PaperSource.paper_id.in_(select(Paper.id).where(research_paper_scope()))).order_by(PaperSource.source, PaperSource.id)).all()
    by_source, attributed, dates, latest_dates = {}, {}, {}, {}
    for record in source_records:
        paper = paper_map[record.paper_id]
        by_source.setdefault(record.source, set()).add(paper.id)
        latest_dates[record.source] = max(latest_dates.get(record.source, paper.first_seen_at), paper.first_seen_at)
        if paper.id not in attributed:
            attributed[paper.id] = record.source
            dates.setdefault(paper.first_seen_at.date(), Counter())[record.source] += 1
    # One primary source per paper; additional evidence is retained separately.
    owned = Counter(attributed.values())
    missing_source = len(papers) - len(attributed)
    if missing_source:
        owned['unknown'] = missing_source
        for p in papers:
            if p.id not in attributed:
                dates.setdefault(p.first_seen_at.date(), Counter())['unknown'] += 1
    processed = db.execute(select(func.coalesce(func.sum(Job.succeeded), 0), func.coalesce(func.sum(Job.failed), 0)).where(Job.kind != 'archive')).one()
    jobs = db.scalars(select(Job).where(Job.kind != 'archive').order_by(Job.created_at.desc(), Job.id.desc()).limit(50)).all()
    venues = Counter(p.venue for p in papers)
    with_abstract = sum(bool((p.abstract or '').strip()) for p in papers)
    latest_sources = {}
    for source in db.scalars(select(PaperSource).where(PaperSource.paper_id.in_([p.id for p in papers[:20]])).order_by(PaperSource.id)):
        latest_sources.setdefault(source.paper_id, []).append(source)
    return {'demo_mode': bool(db.scalar(select(Job.id).where(Job.kind=='demo').limit(1))), 'latest_papers': [{'id': p.id, 'title': p.title, 'authors': json.loads(p.authors_json), 'venue': p.venue, 'year': p.year, 'imported_at': p.first_seen_at, 'homepage_url': paper_homepage(p, latest_sources.get(p.id, []))} for p in papers[:20]],
            'today_papers': by_day[today], 'failed_tasks': db.scalar(select(func.count(Job.id)).where(Job.kind != 'archive', ((Job.status == 'failed') | (Job.failed > 0)))) or 0,
            'venues': [{'name': name, 'papers': count} for name, count in sorted(venues.items())],
            'total_papers': len(papers), 'new_papers': sum(by_day.values()), 'days': days,
            'with_abstract': with_abstract, 'missing_abstract': len(papers)-with_abstract,
            'successful_records': processed[0], 'failed_records': processed[1],
            'source_summary': [{'name': source, 'papers': count, 'last_imported_at': latest_dates.get(source)} for source, count in sorted(owned.items(), key=lambda item: (-item[1], item[0]))],
            'sources': [{'name': source, 'papers': len(ids)} for source, ids in sorted(by_source.items(), key=lambda item: (-len(item[1]), item[0]))],
            'trend': [{'date': (start.date()+timedelta(days=i)).isoformat(), 'papers': by_day[start.date()+timedelta(days=i)], 'sources': dict(dates.get(start.date()+timedelta(days=i), {}))} for i in range(days)],
            'recent_batches': [batch_summary(db, job) for job in jobs], 'timezone': 'UTC'}


def compare_batches(db: Session, first: Job, second: Job) -> dict:
    valid = select(Paper.id).where(research_paper_scope())
    left = select(PaperBatch.paper_id).where(PaperBatch.job_id == first.id, PaperBatch.paper_id.in_(valid))
    right = select(PaperBatch.paper_id).where(PaperBatch.job_id == second.id, PaperBatch.paper_id.in_(valid))
    shared = db.scalar(select(func.count(PaperBatch.paper_id)).where(
        PaperBatch.job_id == first.id, PaperBatch.paper_id.in_(right))) or 0
    a, b = batch_summary(db, first), batch_summary(db, second)
    return {'first': a, 'second': b, 'shared_papers': shared,
            'only_first': a['paper_count'] - shared, 'only_second': b['paper_count'] - shared}


def handoff(db: Session, job: Job) -> dict:
    """Export original evidence, not cleaned titles with mismatched text offsets."""
    from src.knowledge_builder.input_adapter import adapt_openalex_work

    papers = db.scalars(select(Paper).join(PaperBatch, PaperBatch.paper_id == Paper.id)
                        .where(PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope()))).order_by(Paper.id)).all()
    ids = [paper.id for paper in papers]
    sources: dict[int, dict[str, PaperSource]] = {}
    if ids:
        for source in db.scalars(select(PaperSource).where(PaperSource.paper_id.in_(ids)).order_by(PaperSource.id)):
            sources.setdefault(source.paper_id, {})[source.source] = source
    items, excluded = [], []
    for paper in papers:
        records = sources.get(paper.id, {})
        try:
            if 'ecva' in records or 'cvf' in records:
                evidence = json.loads(records['ecva' if 'ecva' in records else 'cvf'].raw_json)
                item = evidence.get('paper_input') if isinstance(evidence, dict) else None
            else:
                item = None
            if item is None and 'openalex' in records:
                raw = json.loads(records['openalex'].raw_json)
                item = asdict(adapt_openalex_work(raw, venue=paper.venue,
                              dataset_id=job.dataset_id or f'batch-{job.id}'))
            if not isinstance(item, dict) or not item.get('openalex_id') or not item.get('abstract') or not item.get('source_url'):
                raise ValueError('missing source, stable identifier or abstract')
            if item['openalex_id'] != paper.openalex_id:
                raise ValueError('source identifier differs from saved paper')
            items.append(item)
        except (KeyError, TypeError, ValueError, AttributeError):
            excluded.append({'paper_id': paper.id, 'title': paper.title, 'reason': '缺少可核对的原始记录、稳定 ID 或摘要'})
    return {'format_version': 'a-paperinput/1', 'batch_id': job.id,
            'batch_code': f'BATCH-{job.id:06d}', 'dataset_id': job.dataset_id,
            'total_papers': len(papers), 'exported_papers': len(items),
            'excluded_papers': len(excluded), 'items': items, 'excluded': excluded}
