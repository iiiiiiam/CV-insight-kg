"""Shared withdrawal controls for manual imports and collected batches."""
import hashlib
import json

from sqlalchemy import select

from .formal_batches import canonical,digest,freeze_content,lock_scope,paper_content,withdraw_batch
from .models import BatchLedger,BatchPaperVersion,Job,JobRecord,Paper,PaperBatch,StablePaper
from .batch_labels import batch_labels


def withdrawal_state(db,job_id):
    job=db.get(Job,job_id)
    if job is None:raise LookupError('批次不存在')
    ledger=db.get(BatchLedger,job_id)
    withdrawn=bool(ledger and ledger.withdrawn)
    supported=job.kind in ('reserve','formal')
    running=job.status in ('queued','running')
    other=db.scalar(select(Job.id).where(Job.id!=job.id,Job.venue==job.venue,Job.year==job.year,Job.status.in_(('queued','running'))).limit(1))
    blocked='请等待本批导入完成' if running else '同一会议年度还有任务正在处理，请稍后再撤回' if other else ''
    return {'batch_id':job_id,'batch_code':f'BATCH-{job_id:06d}',
            **batch_labels(job),
            'state':'withdrawn' if withdrawn else 'active',
            'withdrawal_reason':ledger.withdrawal_reason if ledger else None,
            'withdrawn_at':ledger.withdrawn_at if ledger else None,
            'can_withdraw':supported and not withdrawn and not running and not other,
            'blocked_reason':blocked if supported else '此记录为初始演示批次'}


def retain_legacy_manual_batch(db,job):
    """Add history for manual imports created before versioned imports existed.

    Old manual imports only admitted new papers. Their saved source inputs and
    membership remain available, so withdrawal can preserve IDs and provenance.
    """
    if db.get(BatchLedger,job.id):return
    records=list(db.scalars(select(JobRecord).where(JobRecord.job_id==job.id).order_by(JobRecord.id)))
    key=f'reserve:{job.venue}:{job.year}:{job.id}'
    db.add(BatchLedger(job_id=job.id,batch_key=key,input_sha256=digest([json.loads(r.payload_json) for r in records])))
    for membership in db.scalars(select(PaperBatch).where(PaperBatch.job_id==job.id)):
        paper=db.get(Paper,membership.paper_id)
        identity=db.get(StablePaper,paper.id)
        others=db.scalar(select(PaperBatch.job_id).outerjoin(BatchLedger,BatchLedger.job_id==PaperBatch.job_id).where(
            PaperBatch.paper_id==paper.id,PaperBatch.job_id!=job.id,BatchLedger.job_id.is_(None)).limit(1))
        baseline=canonical(paper_content(paper)) if others is not None or membership.is_new is not True else None
        if identity is None:
            identity=StablePaper(paper_id=paper.id,stable_id='paper:'+hashlib.sha256(paper.canonical_key.encode()).hexdigest(),baseline_json=baseline)
            db.add(identity)
        elif baseline is None:
            # A later managed batch may have treated this old manual import as
            # baseline. Its own version remains a provider after this withdrawal.
            identity.baseline_json=None
        content=freeze_content(db,paper,key)
        # Prefer this batch's original OpenAlex evidence for its historical export.
        source=next((r for r in records if r.source=='openalex' and r.source_id==paper.openalex_id),None)
        if source:
            from .ingest import openalex_work_row
            from src.knowledge_builder.input_adapter import adapt_openalex_work
            from dataclasses import asdict
            saved=json.loads(source.payload_json)
            raw=saved.get('raw',{})
            row=openalex_work_row(raw,job.venue,job.year)
            original=dict(content['paper'])
            for name in ('title','abstract','doi','cited_by_count','source_url','authors'):
                if name in row:original[name]=row[name]
            content['paper']=original
            content['input']=asdict(adapt_openalex_work(raw,venue=job.venue,dataset_id=key))
            content['sources']=[{'source':'openalex','source_id':source.source_id,'source_url':row['source_url'],'raw':raw}]
        db.add(BatchPaperVersion(job_id=job.id,paper_id=paper.id,change_kind='added' if membership.is_new else 'duplicate',
            content_sha256=digest(content),content_json=canonical(content)))
    db.flush()


def withdraw_import(db,job_id,reason):
    job=db.get(Job,job_id)
    if job is None:raise LookupError('批次不存在')
    if job.kind not in ('reserve','formal'):raise ValueError('初始演示批次不支持撤回，请选择手动导入批次')
    lock_scope(db,job.venue,job.year)
    state=withdrawal_state(db,job_id)
    if state['state']=='withdrawn':return state
    if not state['can_withdraw']:raise ValueError(state['blocked_reason'])
    if not reason or not reason.strip():raise ValueError('请填写撤回原因')
    if job.kind=='reserve':retain_legacy_manual_batch(db,job)
    withdraw_batch(db,job_id,reason)
    return withdrawal_state(db,job_id)
