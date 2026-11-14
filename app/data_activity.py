"""Historical additions and immutable withdrawal effects for the daily chart."""
from collections import Counter
import json

from sqlalchemy import select

from .batch_labels import batch_labels,import_mode
from .models import BatchLedger,BatchPaperVersion,BatchWithdrawalAudit,Job,JobEvent,Paper,PaperBatch,PaperSource,StablePaper
from .paper_quality import research_metadata_scope


def additions(db):
    papers={p.id:p for p in db.execute(select(Paper.id,Paper.title,Paper.venue,Paper.year,Paper.first_seen_at).where(research_metadata_scope()))}
    primary={}
    for paper_id,source in db.execute(select(PaperSource.paper_id,PaperSource.source).order_by(PaperSource.source,PaperSource.id)):
        primary.setdefault(paper_id,source)
    values=[];seen=set()
    rows=db.execute(select(PaperBatch,Job,BatchPaperVersion.change_kind).join(Job,Job.id==PaperBatch.job_id)
        .outerjoin(BatchPaperVersion,(BatchPaperVersion.job_id==Job.id)&(BatchPaperVersion.paper_id==PaperBatch.paper_id))
        .where(Job.kind!='archive').order_by(Job.id))
    for membership,job,change in rows:
        paper=papers.get(membership.paper_id)
        if paper is None or (change!='added' if change is not None else membership.is_new is False):continue
        if change is None and paper.id in seen:continue
        when=membership.imported_at if change is not None or job.kind=='demo' else paper.first_seen_at
        values.append({'id':paper.id,'title':paper.title,'venue':paper.venue,'year':paper.year,
            'first_seen_at':when,'batch_id':job.id,**batch_labels(job),'source':primary.get(paper.id,'unknown')})
        seen.add(paper.id)
    for paper in papers.values():
        if paper.id not in seen:
            values.append({'id':paper.id,'title':paper.title,'venue':paper.venue,'year':paper.year,
                'first_seen_at':paper.first_seen_at,'batch_id':None,'import_mode':'automatic','source':primary.get(paper.id,'unknown')})
    return values


def withdrawal_events(db):
    audits={a.job_id:a for a in db.scalars(select(BatchWithdrawalAudit))}
    ledgers={a.job_id:a for a in db.scalars(select(BatchLedger))}
    jobs={j.id:j for j in db.scalars(select(Job))}
    completed={}
    for job_id,at in db.execute(select(JobEvent.job_id,JobEvent.created_at).where(JobEvent.stage=='done').order_by(JobEvent.created_at)):
        completed.setdefault(job_id,at)
    memberships={}
    for paper_id,job_id in db.execute(select(PaperBatch.paper_id,PaperBatch.job_id)):
        memberships.setdefault(paper_id,[]).append(job_id)
    result=[]
    for ledger in ledgers.values():
        if not ledger.withdrawn or not ledger.withdrawn_at:continue
        job=jobs[ledger.job_id];audit=audits.get(job.id)
        if audit:
            removed=json.loads(audit.removed_json);retained=json.loads(audit.retained_json)
        else:
            # Compatibility for withdrawals made before their effect was stored.
            # Actual completion events survive simulated display-date changes.
            removed=[];retained=[]
            for paper_id in db.scalars(select(BatchPaperVersion.paper_id).where(BatchPaperVersion.job_id==job.id)):
                identity=db.get(StablePaper,paper_id)
                providers=[]
                for other in memberships.get(paper_id,[]):
                    if other==job.id:continue
                    other_job=jobs[other];other_ledger=ledgers.get(other)
                    at=completed.get(other,other_job.finished_at or other_job.created_at)
                    if at<=ledger.withdrawn_at and not (other_ledger and other_ledger.withdrawn_at and other_ledger.withdrawn_at<=ledger.withdrawn_at):providers.append(other)
                (retained if providers or (identity and identity.baseline_json) else removed).append(paper_id)
        result.append({'batch_id':job.id,'batch_code':f'BATCH-{job.id:06d}',**batch_labels(job),
            'withdrawn_at':ledger.withdrawn_at,'reason':ledger.withdrawal_reason,
            'removed_papers':len(removed),'retained_papers':len(retained),'paper_ids':removed,'retained_ids':retained})
    return result


def freeze_legacy_withdrawals(db):
    missing=db.scalar(select(BatchLedger.job_id).outerjoin(BatchWithdrawalAudit,BatchWithdrawalAudit.job_id==BatchLedger.job_id)
        .where(BatchLedger.withdrawn.is_(True),BatchWithdrawalAudit.job_id.is_(None)).limit(1))
    if missing is None:return
    existing=set(db.scalars(select(BatchWithdrawalAudit.job_id)))
    for item in withdrawal_events(db):
        if item['batch_id'] not in existing:
            db.add(BatchWithdrawalAudit(job_id=item['batch_id'],occurred_at=item['withdrawn_at'],
                removed_json=json.dumps(item['paper_ids']),retained_json=json.dumps(item['retained_ids']),reconstructed=True))
    db.commit()


def activity_summary(db):
    added=additions(db);withdrawn=withdrawal_events(db)
    counts=Counter();modes={};removed=Counter();batches=Counter()
    for item in added:
        day=item['first_seen_at'].date();counts[day]+=1
        modes.setdefault(day,Counter())[item['import_mode']]+=1
    for item in withdrawn:
        day=item['withdrawn_at'].date();removed[day]+=item['removed_papers'];batches[day]+=1
    return counts,modes,removed,batches
