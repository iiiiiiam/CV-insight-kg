"""Automatic batch delivery, import recovery and non-destructive A/B reconciliation."""
from datetime import timedelta
import json
import os

from sqlalchemy import select
from sqlalchemy.orm import defer

from .models import BatchLedger, HandoffReconciliation, Job, JobEvent, Source, WorkflowTask, now


def enabled():
    return os.getenv('A_AUTO_HANDOFF', 'true').lower() not in ('0', 'false', 'off')


def queue_delivery(db, document, *, repair=False):
    from .workflow_tasks import enqueue, view
    identifier, revision = document['batch_id'], document['batch_revision']
    task = db.scalar(select(WorkflowTask).options(defer(WorkflowTask.payload_json)).where(
        WorkflowTask.kind == 'handoff', WorkflowTask.batch_id == identifier,
        WorkflowTask.batch_revision == revision).order_by(WorkflowTask.created_at).limit(1))
    if task is None:
        task, _ = enqueue(db, 'handoff', f'auto:{identifier}:{revision}',
            dict(batch_id=identifier, batch_revision=revision, action=document['state']),
            dict(batch_id=identifier, batch_revision=revision, document=document), commit=False)
        task.automatic, task.retryable, task.max_attempts = True, True, 5
    elif not task.automatic:
        task.automatic = True
        if task.status=='failed':
            task.retryable, task.next_attempt_at, task.max_attempts = True, now(), task.attempts+5
    if repair and task.status == 'succeeded':
        from .workflow_tasks import event
        task.status, task.error, task.finished_at = 'queued', None, None
        task.max_attempts = task.attempts + 5
        task.next_attempt_at = None
        task.automatic, task.retryable = True, True
        event(task, 'queued', 0, '对账发现 B 批次缺失或撤回未同步，自动补交')
    db.flush()
    return view(task)


def schedule_import_retry(job, db=None):
    if job.kind not in ('formal', 'reserve', 'online'):
        return
    if db is not None:
        from .models import CollectionTask
        if db.scalar(select(CollectionTask.id).where(CollectionTask.job_id==job.id).limit(1)):
            job.next_retry_at=None
            return  # Scheduled imports retain their collection task's retry budget.
    if job.status == 'succeeded':
        job.next_retry_at = None
    elif enabled() and job.status in ('failed', 'partial') and (job.retry_attempts or 0) < 3:
        job.next_retry_at = now() + timedelta(seconds=30 * 2 ** (job.retry_attempts or 0))


def scan(db):
    """Recover omissions locally; never treat old sample/demo jobs as formal imports."""
    if not enabled():
        return
    from .formal_batches import batch_manifest, lock_scope
    from .delivery import queue_withdrawal_notification
    jobs = db.scalars(select(Job).join(BatchLedger, BatchLedger.job_id == Job.id)
        .where(Job.kind.in_(('formal', 'reserve'))).order_by(Job.id)).all()
    for job in jobs:
        ledger = db.get(BatchLedger, job.id)
        if ledger.withdrawn:
            queue_withdrawal_notification(db, batch_manifest(db, job.id))
        elif job.status == 'succeeded':
            queue_delivery(db, batch_manifest(db, job.id))
        elif job.status in ('partial', 'failed'):
            from .models import CollectionTask
            if db.scalar(select(CollectionTask.id).where(CollectionTask.job_id==job.id).limit(1)):
                job.next_retry_at=None
                continue
            if job.next_retry_at is None:
                schedule_import_retry(job,db)
            if job.next_retry_at is None or job.next_retry_at > now():
                continue
            source = db.scalar(select(Source).where(Source.name == job.source))
            if source is not None and not source.enabled:
                continue
            lock_scope(db, job.venue, job.year)
            busy = db.scalar(select(Job.id).where(Job.id != job.id, Job.venue == job.venue,
                Job.year == job.year, Job.status.in_(('queued', 'running'))).limit(1))
            if busy:
                continue
            job.retry_attempts = (job.retry_attempts or 0) + 1
            job.status, job.stage, job.active_key = 'queued', 'queued', f'{job.venue}:{job.year}'
            job.next_retry_at, job.finished_at = None, None
            db.add(JobEvent(job_id=job.id, stage='queued', level='info',
                message=f'自动重试导入失败记录，第 {job.retry_attempts} 次；已成功记录保留'))
    # A live request that failed before freezing a formal batch keeps its own
    # saved selection and page cursor; no full-year download is started.
    from .models import OnlineCollection
    for job in db.scalars(select(Job).join(OnlineCollection,OnlineCollection.job_id==Job.id)
                          .where(Job.kind=='online',Job.status=='failed').order_by(Job.id)):
        if job.next_retry_at is None:schedule_import_retry(job,db)
        if job.next_retry_at is None or job.next_retry_at>now():continue
        source=db.scalar(select(Source).where(Source.name==job.source))
        if source is not None and not source.enabled:continue
        lock_scope(db,job.venue,job.year)
        if db.scalar(select(Job.id).where(Job.id!=job.id,Job.venue==job.venue,Job.year==job.year,
                                         Job.status.in_(('queued','running'))).limit(1)):continue
        job.status,job.stage,job.active_key='queued','queued',f'{job.venue}:{job.year}'
        job.retry_attempts+=1;job.next_retry_at=None;job.finished_at=None
        db.add(JobEvent(job_id=job.id,stage='queued',level='info',message='自动重试本次在线采集，继续使用已保存进度'))
    db.commit()


def reconciliation_view(db):
    row = db.get(HandoffReconciliation, 'B')
    return dict(status=row.status if row else 'waiting', checked_at=row.checked_at if row else None,
        next_check_at=row.next_check_at if row else None, error=row.error if row else None,
        summary=json.loads(row.summary_json) if row else {})


def reconcile(db, remote):
    """Compare batch identities/state and exact input digests; never withdraw foreign batches."""
    from .formal_batches import batch_manifest
    from .delivery import queue_withdrawal_notification, owns_remote_batch
    from src.knowledge_builder.extraction import fingerprint
    known = {b['batch_code']: b for b in remote['batches']}
    summary = dict(matched=[], repair_queued=[], conflicts=[], unverified=[], unmanaged_b_batches=[])
    local_codes = set()
    for job in db.scalars(select(Job).join(BatchLedger, BatchLedger.job_id == Job.id)
                         .where(Job.kind.in_(('formal', 'reserve'))).order_by(Job.id)):
        ledger = db.get(BatchLedger, job.id)
        document = batch_manifest(db, job.id)
        code, target = document['batch_code'], known.get(document['batch_code'])
        local_codes.add(code)
        if ledger.withdrawn:
            if target and target['active']:
                if not owns_remote_batch(db,job.id,target):
                    summary['conflicts'].append(dict(batch_code=code,reason='B 同编号批次与 A 原始交接内容不一致'))
                    continue
                notification = queue_withdrawal_notification(db, document, repair=True)
                if notification['status'] == 'not_required':
                    summary['conflicts'].append(dict(batch_code=code, reason='B 有同编号批次，但 A 无交接记录，需核对来源'))
                else:
                    summary['repair_queued'].append(dict(batch_code=code, task_id=notification['id'], state='withdrawn'))
            else:
                summary['matched'].append(code)
                confirm_reconciled(db, document, remote)
        elif job.status == 'succeeded':
            if target is None:
                if any(b.get('active') and b.get('batch_id',0)>job.id for b in known.values()):
                    summary['conflicts'].append(dict(batch_code=code,reason='旧批次缺失，需恢复 B 账本以保留版本优先级'))
                    continue
                task = queue_delivery(db, document, repair=True)
                if task['status']=='failed' and task['next_attempt_at'] is None:
                    summary['conflicts'].append(dict(batch_code=code,reason='自动交接重试已结束，请处理失败原因'))
                else:
                    summary['repair_queued'].append(dict(batch_code=code, task_id=task['id'], state='active'))
            elif not target['active']:
                summary['conflicts'].append(dict(batch_code=code, reason='B 已独立撤回；保留 B 决定，不自动恢复'))
            elif target.get('handoff_digest') is None:
                summary['unverified'].append(dict(batch_code=code, reason='B 状态接口尚未提供输入指纹'))
            elif target['handoff_digest'] != fingerprint(document):
                summary['conflicts'].append(dict(batch_code=code, reason='同编号批次的输入指纹不一致'))
            else:
                summary['matched'].append(code)
                confirm_reconciled(db, document, remote)
    summary['unmanaged_b_batches'] = sorted(set(known) - local_codes)
    summary['b_snapshot_revision'] = remote['snapshot_revision']
    return summary


def confirm_reconciled(db, document, remote):
    """Recover an acknowledgement lost between B's commit and A's receipt write."""
    from .operations import HandoffReceipt
    from .workflow_tasks import encode, event
    task = db.scalar(select(WorkflowTask).where(WorkflowTask.kind=='handoff',
        WorkflowTask.batch_id==document['batch_id'], WorkflowTask.batch_revision==document['batch_revision'])
        .order_by(WorkflowTask.created_at).limit(1))
    if task is None or task.status in ('succeeded', 'running'):
        return
    receipt = db.scalar(select(HandoffReceipt).where(HandoffReceipt.job_id==document['batch_id'],
        HandoffReceipt.revision==document['batch_revision'], HandoffReceipt.recipient=='B'))
    if receipt is None:
        receipt=HandoffReceipt(job_id=document['batch_id'],revision=document['batch_revision'],recipient='B',status='received')
        db.add(receipt)
    receipt.snapshot_revision=remote['snapshot_revision']
    receipt.message='自动对账已核对 B 批次状态与当前交接版本'
    task.status,task.error,task.finished_at,task.next_attempt_at='succeeded',None,now(),None
    task.result_json=encode(dict(batch_id=document['batch_id'],batch_revision=document['batch_revision'],
        batch_state=document['state'],b_status='unchanged',b_paper_count=remote['paper_count'],
        b_snapshot_revision=remote['snapshot_revision'],received=True,reconciled=True,
        knowledge_processing='pending_check',graph_publication='pending_check'))
    event(task,'completed',100,'自动对账确认 B 已生效，补回 A 的接收回执')


def maintain(factory, *, http_factory=None):
    """Called on worker startup and periodically while retaining its existing lock."""
    if not enabled():
        return
    with factory() as db:
        scan(db)
        state = db.get(HandoffReconciliation, 'B')
        if state and state.next_check_at and state.next_check_at > now():
            return
        if state is None:
            state = HandoffReconciliation(id='B')
            db.add(state)
        # Release DB writes before HTTP. A restart can retry an interrupted check.
        db.commit()
        try:
            from .delivery import b_session
            with b_session(http_factory) as request:
                remote = request('GET', '/api/admin/knowledge/batches')
            summary = reconcile(db, remote)
            state.status = 'attention' if summary['conflicts'] or summary['unverified'] else (
                'repairing' if summary['repair_queued'] else 'synchronized')
            state.summary_json = json.dumps(summary, ensure_ascii=False)
            state.error, state.failures = None, 0
            delay = 60
        except Exception as exc:
            db.rollback()
            state = db.get(HandoffReconciliation, 'B')
            state.status = 'unavailable'
            # Do not put URL/credential-bearing network exceptions in the API.
            state.error = '暂无法与 B 对账，保留已有回执和结果，稍后自动重试'
            state.failures = (state.failures or 0) + 1
            delay = min(300, 30 * 2 ** min(state.failures - 1, 4))
        state.checked_at = now()
        state.next_check_at = now() + timedelta(seconds=delay)
        db.commit()
