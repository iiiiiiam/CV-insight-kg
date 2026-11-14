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
from .batch_labels import batch_labels,import_mode


def has_batch_history(db:Session,job:Job)->bool:
    from .models import BatchLedger
    return job.kind=='formal' or (job.kind=='reserve' and db.get(BatchLedger,job.id) is not None)


def frozen_batch_papers(db: Session, job_id: int) -> list[dict]:
    from .models import BatchPaperVersion
    return [json.loads(v.content_json)['paper'] | {'id': v.paper_id, 'batch_ids': [job_id]}
            for v in db.scalars(select(BatchPaperVersion).where(BatchPaperVersion.job_id == job_id).order_by(BatchPaperVersion.paper_id))]


def batch_paper_ids(db: Session, job: Job) -> set[int]:
    if has_batch_history(db,job):
        from .models import BatchPaperVersion
        return set(db.scalars(select(BatchPaperVersion.paper_id).where(BatchPaperVersion.job_id == job.id)))
    return set(db.scalars(select(PaperBatch.paper_id).where(PaperBatch.job_id == job.id,
        PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())))))


def batch_summary(db: Session, job: Job) -> dict:
    count,new=0,None
    if not has_batch_history(db,job):
        count = db.scalar(select(func.count(PaperBatch.paper_id)).where(PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())))) or 0
        unknown = db.scalar(select(func.count(PaperBatch.paper_id)).where(
            PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())), PaperBatch.is_new.is_(None))) or 0
        new = None if unknown else (db.scalar(select(func.count(PaperBatch.paper_id)).where(
            PaperBatch.job_id == job.id, PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())), PaperBatch.is_new.is_(True))) or 0)
    extra={}
    if has_batch_history(db,job):
        from .models import BatchLedger,BatchPaperVersion,JobRecord
        counts=Counter(db.scalars(select(BatchPaperVersion.change_kind).where(BatchPaperVersion.job_id==job.id)))
        count=sum(counts.values());new=counts['added'];extra={'duplicate_papers':counts['duplicate'],'updated_papers':counts['updated'],'source_names':sorted(set(db.scalars(select(JobRecord.source).where(JobRecord.job_id==job.id)))),'batch_state':'withdrawn' if db.get(BatchLedger,job.id).withdrawn else 'active'}
    return {'id': job.id, 'batch_code': f'BATCH-{job.id:06d}', **batch_labels(job),'dataset_id': job.dataset_id,
            'venue': job.venue, 'year': job.year, 'source': job.source, 'status': job.status,
            'stage': job.stage, 'attempted': job.attempted, 'succeeded': job.succeeded,
            'failed': job.failed, 'paper_count': count, 'new_papers': new,
            'duplicate_papers': None if new is None else max(0, job.succeeded-new), 'kind': job.kind,
            'created_at': job.created_at, 'started_at': job.started_at, 'finished_at': job.finished_at, **extra}


def dashboard(db: Session, days: int = 7) -> dict:
    today = now().date()
    start = datetime.combine(today - timedelta(days=days - 1), time.min)
    end = datetime.combine(today + timedelta(days=1), time.min)
    from .data_activity import activity_summary
    added,added_modes,withdrawn,withdrawn_batches=activity_summary(db)
    papers = db.execute(select(Paper.id,Paper.venue,Paper.first_seen_at,(func.length(func.trim(func.coalesce(Paper.abstract,'')))>0).label('abstract')).where(research_paper_scope()).order_by(Paper.first_seen_at.desc(), Paper.id.desc())).all()
    latest_papers = db.scalars(select(Paper).where(Paper.id.in_([p.id for p in papers[:20]])).order_by(Paper.first_seen_at.desc(),Paper.id.desc())).all()
    paper_map = {p.id: p for p in papers}
    by_day = Counter(p.first_seen_at.date() for p in papers if start <= p.first_seen_at < end)
    # Count each paper under its first providing batch. Additional sources and
    # repeated imports never double the daily totals.
    from .models import BatchLedger
    providers=db.execute(select(PaperBatch.paper_id,Job).join(Job,Job.id==PaperBatch.job_id)
        .outerjoin(BatchLedger,BatchLedger.job_id==Job.id)
        .where(PaperBatch.paper_id.in_(select(Paper.id).where(research_paper_scope())),Job.kind!='archive',
               (BatchLedger.withdrawn.is_(False)|BatchLedger.job_id.is_(None)))
        .order_by(PaperBatch.imported_at,Job.id)).all()
    modes={};daily_modes={}
    for paper_id,job in providers:modes.setdefault(paper_id,import_mode(job))
    for paper in papers:
        day=paper.first_seen_at.date()
        daily_modes.setdefault(day,Counter())[modes.get(paper.id,'automatic')]+=1
    source_records = db.execute(select(PaperSource.paper_id, PaperSource.source).where(PaperSource.paper_id.in_(select(Paper.id).where(research_paper_scope()))).order_by(PaperSource.source, PaperSource.id)).all()
    by_source, attributed, dates, latest_dates = {}, {}, {}, {}
    for record in source_records:
        paper = paper_map.get(record.paper_id)
        if paper is None:continue  # A concurrent import may have committed after the paper query.
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
    with_abstract = sum(bool(p.abstract) for p in papers)
    latest_sources = {}
    for source in db.scalars(select(PaperSource).where(PaperSource.paper_id.in_([p.id for p in papers[:20]])).order_by(PaperSource.id)):
        latest_sources.setdefault(source.paper_id, []).append(source)
    return {'demo_mode': bool(db.scalar(select(Job.id).where(Job.kind=='demo').limit(1))), 'latest_papers': [{'id': p.id, 'title': p.title, 'authors': json.loads(p.authors_json), 'venue': p.venue, 'year': p.year, 'imported_at': p.first_seen_at, 'homepage_url': paper_homepage(p, latest_sources.get(p.id, []))} for p in latest_papers],
            'today_papers': by_day[today], 'today_added_papers':added[today],'today_withdrawn_papers':withdrawn[today],
            'today_net_papers':added[today]-withdrawn[today],
            'failed_tasks': db.scalar(select(func.count(Job.id)).where(Job.kind != 'archive', ((Job.status == 'failed') | (Job.failed > 0)))) or 0,
            'venues': [{'name': name, 'papers': count} for name, count in sorted(venues.items())],
            'total_papers': len(papers), 'new_papers': sum(by_day.values()), 'days': days,
            'with_abstract': with_abstract, 'missing_abstract': len(papers)-with_abstract,
            'successful_records': processed[0], 'failed_records': processed[1],
            'source_summary': [{'name': source, 'papers': count, 'last_imported_at': latest_dates.get(source)} for source, count in sorted(owned.items(), key=lambda item: (-item[1], item[0]))],
            'sources': [{'name': source, 'papers': len(ids)} for source, ids in sorted(by_source.items(), key=lambda item: (-len(item[1]), item[0]))],
            'trend': [{'date': (start.date()+timedelta(days=i)).isoformat(), 'papers': by_day[start.date()+timedelta(days=i)], 'sources': dict(dates.get(start.date()+timedelta(days=i), {})),
                       'added_papers':added[start.date()+timedelta(days=i)],
                       'added_import_modes':{mode:added_modes.get(start.date()+timedelta(days=i),{}).get(mode,0) for mode in ('manual','automatic')},
                       'withdrawn_papers':withdrawn[start.date()+timedelta(days=i)],'withdrawn_batches':withdrawn_batches[start.date()+timedelta(days=i)],
                       'net_papers':added[start.date()+timedelta(days=i)]-withdrawn[start.date()+timedelta(days=i)],
                       'import_modes':{mode:daily_modes.get(start.date()+timedelta(days=i),{}).get(mode,0) for mode in ('manual','automatic')}} for i in range(days)],
            'recent_batches': [batch_summary(db, job) for job in jobs], 'timezone': 'UTC'}


def compare_batches(db: Session, first: Job, second: Job) -> dict:
    left, right = batch_paper_ids(db, first), batch_paper_ids(db, second)
    shared = len(left & right)
    a, b = batch_summary(db, first), batch_summary(db, second)
    return {'first': a, 'second': b, 'shared_papers': shared,
            'only_first': len(left - right), 'only_second': len(right - left)}


def handoff(db: Session, job: Job) -> dict:
    """Export original evidence, not cleaned titles with mismatched text offsets."""
    if has_batch_history(db,job):
        from .formal_batches import batch_manifest
        return batch_manifest(db,job.id)
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
            'batch_code': f'BATCH-{job.id:06d}', **batch_labels(job),'dataset_id': job.dataset_id,
            'total_papers': len(papers), 'exported_papers': len(items),
            'excluded_papers': len(excluded), 'items': items, 'excluded': excluded}
