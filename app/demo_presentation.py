"""Prepare editable preview batches from genuine locally stored papers."""
from collections import defaultdict
from datetime import datetime,timedelta
import json

from sqlalchemy import select

from .models import BatchLedger,Job,JobEvent,Paper,PaperBatch,PaperSource,now
from .paper_quality import research_paper_scope


def rebuild_history(db):
    """Balance only initial demonstration history; keep real imported batches."""
    demo_ids=list(db.scalars(select(Job.id).where(Job.kind=='demo')))
    scope=[research_paper_scope()]
    if demo_ids:
        scope.append(Paper.id.in_(select(PaperBatch.paper_id).where(PaperBatch.job_id.in_(demo_ids))))
    elif db.scalar(select(Job.id).where(Job.kind=='reserve').limit(1)) is not None:
        raise ValueError('This database has no initial preview history')
    papers=list(db.scalars(select(Paper).where(*scope).order_by(Paper.id)))
    source_map=defaultdict(set)
    for paper_id,source in db.execute(select(PaperSource.paper_id,PaperSource.source)):
        source_map[paper_id].add(source)
    for job in db.scalars(select(Job).where(Job.kind.in_(('demo','sample')))):job.kind='archive'
    buckets=defaultdict(list)
    for i,paper in enumerate(papers):
        day=i%14
        mode='manual' if ((i//14)+day)%5<2 else 'automatic'
        sources=source_map[paper.id]
        source=next((s for s in ('ecva','cvf','openalex','dblp') if s in sources),'openalex')
        buckets[(paper.venue,paper.year,source,day,mode)].append(paper)
    for (venue,year,source,index,mode),items in sorted(buckets.items()):
        day=datetime.combine(now().date()-timedelta(days=13-index),datetime.min.time())+timedelta(hours=9)
        job=Job(venue=venue,year=year,source=source,kind='demo',import_mode=mode,is_simulated=True,
            dataset_id=f'demo-{mode}-{venue}-{year}-{day.date()}',status='succeeded',stage='done',
            attempted=len(items),succeeded=len(items),failed=0,created_at=day,started_at=day,finished_at=day+timedelta(minutes=4))
        db.add(job);db.flush()
        for paper in items:
            paper.first_seen_at=day
            db.add(PaperBatch(job_id=job.id,paper_id=paper.id,is_new=True,imported_at=day))
        db.add(JobEvent(job_id=job.id,stage='done',level='info',message='演示历史：真实论文，导入方式和日期为模拟展示。',created_at=day))
    db.commit()
    return len(papers)


def prepare_withdrawable(factory,minimum=12,existing_ids=()):
    """Create small actual imports, then arrange their preview dates and modes."""
    from .reserve import queue_import,summary
    from .ingest import run_job
    if not 2<=minimum<=30:raise ValueError('Choose 2–30 preview batches')
    with factory() as db:
        if db.scalar(select(Job.id).where(Job.kind=='demo').limit(1)) is None:
            raise ValueError('Use an isolated preview database')
        if db.scalar(select(Job.id).where(Job.status.in_(('queued','running'))).limit(1)) is not None:
            raise ValueError('Wait for running imports to finish')
        jobs=list(db.scalars(select(Job).join(BatchLedger,BatchLedger.job_id==Job.id).where(
            Job.kind=='reserve',BatchLedger.withdrawn.is_(False),
            (Job.is_simulated.is_(True)|Job.id.in_(existing_ids))).order_by(Job.id)))
        created=[]
        for i in range(max(0,minimum-len(jobs))):
            groups=summary(db)['items']
            venue='CVPR' if i%2==0 else 'ICCV'
            group=next(g for g in groups if g['venue']==venue and g['available']>=8)
            job,_=queue_import(db,group['venue'],group['year'],group['source'],8)
            job.import_mode='manual' if i%2==0 else 'automatic'
            job.is_simulated=True;db.commit()
            run_job(db,job)
            if job.status!='succeeded':raise ValueError(f'Preview import {job.id} did not complete')
            jobs.append(job);created.append(job.id)
        dates=[]
        for i,job in enumerate(jobs):
            day=datetime.combine(now().date()-timedelta(days=13-i%14),datetime.min.time())+timedelta(hours=10,minutes=10*(i//14))
            original=job.created_at
            job.is_simulated=True
            if not job.import_mode:job.import_mode='manual'
            job.created_at=job.started_at=day;job.finished_at=day+timedelta(minutes=2)
            for membership in db.scalars(select(PaperBatch).where(PaperBatch.job_id==job.id)):
                membership.imported_at=day
                db.get(Paper,membership.paper_id).first_seen_at=day
            db.add(JobEvent(job_id=job.id,stage='demo',level='info',message=json.dumps({
                'note':'本地真实论文导入；方式和日期用于模拟展示，未启动在线定时采集。',
                'actual_created_at':original.isoformat(),'simulated_at':day.isoformat(),'import_mode':job.import_mode},ensure_ascii=False)))
            dates.append({'id':job.id,'mode':job.import_mode,'date':day.isoformat()})
        db.commit()
        return {'created_ids':created,'prepared_batches':dates,'available_papers':summary(db)['available']}
