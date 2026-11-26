"""Schedule settings and durable run controls using the existing A auth boundary."""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from .models import CollectionSchedule, CollectionRun, CollectionTask, BatchLedger, now
from .scheduler import (TERMINAL, default_config, validate_config, slot, new_run, status)
from .formal_batches import canonical, digest


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    time: str = Field(pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone: str = Field(default='Asia/Shanghai', min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=12)
    with_annotations: bool = True
    max_attempts: int = Field(default=3, ge=1, le=8)
    retry_seconds: int = Field(default=300, ge=1, le=86400)
    expected_revision: str | None = Field(default=None, pattern='^[0-9a-f]{64}$')


def create_scheduler_router(db_session, admin):
    router = APIRouter(prefix='/api/admin/formal', dependencies=[Depends(admin)])

    def factory(db):
        return sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    def lock(db):
        connection = db.connection()
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')

    @router.get('/schedules')
    def schedules(limit: int = Query(20, ge=1, le=100), db=Depends(db_session)):
        return status(factory(db), limit=limit)

    @router.put('/schedules/{identifier}')
    def save(identifier: str, body: ScheduleUpdate, db=Depends(db_session)):
        lock(db)
        saved = db.scalar(select(CollectionSchedule).where(CollectionSchedule.id == identifier).with_for_update())
        old = json.loads(saved.config_json) if saved else default_config()
        if saved and body.expected_revision != digest(old):
            raise HTTPException(409, '定时计划已变化，请重新读取后保存')
        try:
            config = validate_config(old | body.model_dump(exclude={'expected_revision'}) | {'id': identifier})
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if saved is None:
            saved = CollectionSchedule(id=identifier, instance_key=uuid.uuid4().hex,
                next_run_at=slot(now(), config, next_slot=True))
            db.add(saved)
        elif (old['time'], old['timezone']) != (config['time'], config['timezone']) or (config['enabled'] and not saved.enabled):
            saved.next_run_at = slot(now(), config, next_slot=True)
        saved.config_json, saved.enabled = canonical(config), config['enabled']
        saved.updated_at = now()
        db.commit()
        return status(factory(db))

    @router.post('/schedules/{identifier}/run', status_code=202)
    def run(identifier: str, db=Depends(db_session)):
        lock(db)
        schedule = db.scalar(select(CollectionSchedule).where(CollectionSchedule.id == identifier).with_for_update())
        if schedule is None:
            raise HTTPException(404, '请先保存定时计划')
        active = db.scalar(select(CollectionRun).where(CollectionRun.schedule_id == identifier,
            CollectionRun.status.not_in(TERMINAL)).order_by(CollectionRun.id.desc()).limit(1))
        if active:
            return {'run_id': active.id, 'replay': True}
        created = new_run(db, schedule, now().replace(microsecond=0), 'manual')
        db.commit()
        return {'run_id': created.id, 'replay': False}

    @router.post('/collection-runs/{identifier}/retry', status_code=202)
    def retry(identifier: int, db=Depends(db_session)):
        lock(db)
        saved = db.scalar(select(CollectionRun).where(CollectionRun.id == identifier).with_for_update())
        if saved is None:
            raise HTTPException(404, '未找到定时采集记录')
        if saved.status not in ('failed', 'partial'):
            raise HTTPException(409, '只能重试失败或部分失败的运行记录')
        retried = 0
        for task in db.scalars(select(CollectionTask).where(CollectionTask.run_id == identifier,
                                                           CollectionTask.status.in_(('failed', 'partial')))):
            ledger = db.get(BatchLedger, task.job_id) if task.job_id else None
            if ledger and ledger.withdrawn:
                task.status = 'cancelled'
                continue
            task.retry_round += 1
            task.status, task.error, task.next_attempt_at = 'retry_wait', None, now()
            retried += 1
        if not retried:
            raise HTTPException(409, '没有可重试的失败记录；已撤回的批次不会重新启用')
        saved.status, saved.finished_at = 'queued', None
        db.commit()
        return {'run_id': identifier, 'retried_tasks': retried}
    return router
