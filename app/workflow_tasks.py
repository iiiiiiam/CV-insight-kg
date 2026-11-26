"""Durable tasks sharing A's single-worker lifecycle and administrator boundary."""
import hashlib
import json
import uuid
from datetime import timedelta

from sqlalchemy import select, update, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from .models import WorkflowTask, now


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def view(task):
    return dict(id=task.id, kind=task.kind, title=task.title,
                batch_id=task.batch_id, batch_revision=task.batch_revision,
                status=task.status, stage=task.stage, progress=task.progress, attempts=task.attempts,
                created_at=task.created_at, updated_at=task.updated_at, finished_at=task.finished_at,
                error=task.error, result=json.loads(task.result_json) if task.result_json else None,
                automatic=task.automatic, retryable=task.retryable, max_attempts=task.max_attempts,
                next_attempt_at=task.next_attempt_at,
                events=json.loads(task.events_json))


def event(task, stage, progress, message):
    task.stage, task.progress, task.updated_at = stage, progress, now()
    history = json.loads(task.events_json or '[]')
    history.append(dict(at=task.updated_at.isoformat(), attempt=task.attempts,
                        stage=stage, progress=progress, message=message))
    task.events_json = encode(history[-200:])


def existing(db, kind, request_key, request):
    key = digest([kind, request_key])
    task = db.scalar(select(WorkflowTask).options(defer(WorkflowTask.payload_json)).where(WorkflowTask.request_key == key))
    if task and task.request_sha256 != digest(request):
        raise ValueError('同一 request_key 的参数已变化，请使用新的请求编号')
    return task


def enqueue(db, kind, request_key, request, payload, *, commit=True):
    task = existing(db, kind, request_key, request)
    if task:
        return task, True
    task = WorkflowTask(id=uuid.uuid4().hex, kind=kind, request_key=digest([kind, request_key]),
                        request_sha256=digest(request), payload_json=encode(payload), events_json='[]',
                        title=payload.get('title'), batch_id=payload.get('batch_id'),
                        batch_revision=payload.get('batch_revision'))
    db.add(task)
    if not commit:
        db.flush()
        return task, False
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        task = existing(db, kind, request_key, request)
        if task is None:
            raise
        return task, True
    return task, False


def retry(db, task):
    result = db.execute(update(WorkflowTask).where(WorkflowTask.id == task.id,
        WorkflowTask.status == 'failed').values(status='queued', stage='queued', progress=0,
        error=None, finished_at=None, updated_at=now(), next_attempt_at=None,
        max_attempts=task.attempts+5 if task.kind=='handoff' else task.max_attempts,
        retryable=task.kind=='handoff'))
    if not result.rowcount:
        db.rollback()
        raise ValueError('只能重试失败任务；运行中或已完成的任务保持原状态')
    db.commit()
    db.refresh(task, attribute_names=['status', 'stage', 'progress', 'attempts', 'error',
        'finished_at', 'updated_at', 'events_json', 'result_json', 'next_attempt_at', 'max_attempts', 'retryable'])
    return task


def recover(factory):
    with factory() as db:
        for task in db.scalars(select(WorkflowTask).where(WorkflowTask.status == 'running')):
            task.status, task.error = 'queued', None
            event(task, 'queued', 0, '服务恢复，继续使用原任务的冻结输入')
        db.commit()


def run_one(factory):
    """CAS-claim a task; callers hold A's existing worker lock."""
    with factory() as db:
        eligible = or_(WorkflowTask.status=='queued', and_(WorkflowTask.status=='failed',
            WorkflowTask.automatic.is_(True), WorkflowTask.retryable.is_(True),
            WorkflowTask.next_attempt_at<=now(), WorkflowTask.attempts<WorkflowTask.max_attempts))
        identifier = db.scalar(select(WorkflowTask.id).where(eligible)
                               .order_by(WorkflowTask.created_at, WorkflowTask.batch_id, WorkflowTask.id).limit(1))
        if identifier is None:
            return False
        claimed = db.execute(update(WorkflowTask).where(WorkflowTask.id == identifier,
            eligible).values(status='running', attempts=WorkflowTask.attempts + 1,
            updated_at=now(), error=None, next_attempt_at=None))
        db.commit()
        if not claimed.rowcount:
            return False
        task = db.get(WorkflowTask, identifier)
        def checkpoint(stage, progress, message):
            event(task, stage, progress, message)
            db.commit()
        try:
            payload = json.loads(task.payload_json)
            if task.kind == 'report':
                from .report_bundle import generate
                result = generate(task, payload, checkpoint)
            elif task.kind == 'handoff':
                from .delivery import send
                result = send(db, payload, checkpoint)
            else:
                raise ValueError('未知任务类型')
            task.result_json = encode(result)
            task.status, task.error, task.finished_at = 'succeeded', None, now()
            event(task, 'completed', 100, '任务完成')
            db.commit()
        except Exception as exc:
            db.rollback()
            task = db.get(WorkflowTask, identifier)
            from .pipeline import safe_error
            # Network exceptions can contain private URLs; expose stable messages instead.
            import requests
            task.error = ('接收服务连接失败，请检查服务后重试' if isinstance(exc, requests.RequestException)
                          else safe_error(exc))
            task.status, task.finished_at = 'failed', now()
            task.retryable = task.kind=='handoff' and getattr(exc, 'retryable',
                not isinstance(exc, (KeyError, TypeError)))
            task.next_attempt_at = (now()+timedelta(seconds=min(300,30*2**min(task.attempts-1,4)))
                if task.automatic and task.retryable and task.attempts<task.max_attempts else None)
            event(task, 'failed', task.progress, task.error)
            db.commit()
        return True
