"""A report and one-click delivery APIs; long work runs in the existing worker."""
import hashlib
import json
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import defer

from .models import WorkflowTask
from .workflow_tasks import enqueue, existing, retry, view


class ReportScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_ids: list[int] = Field(default_factory=list, max_length=100)
    venues: list[Literal['CVPR', 'ICCV', 'ECCV']] = Field(default_factory=list, max_length=3)
    years: list[int] = Field(default_factory=list, max_length=50)
    paper_ids: list[str] = Field(default_factory=list, max_length=50000)


class ReportSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['B', 'C']
    revision: str = Field(min_length=1, max_length=200)
    paper_ids: list[str] = Field(max_length=50000)
    data: dict


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=180)
    title: str = Field(default='论文数据报告', min_length=1, max_length=200)
    scope: ReportScope = Field(default_factory=ReportScope)
    sections: list[ReportSection] = Field(default_factory=list, max_length=2)



def create_workflow_router(db_session, admin):
    router = APIRouter(prefix='/api/admin', dependencies=[Depends(admin)])

    def get(db, identifier, kind):
        task = db.get(WorkflowTask, identifier, options=[defer(WorkflowTask.payload_json)])
        if task is None or task.kind != kind:
            raise HTTPException(404, '未找到任务')
        return task

    def listing(db, kind, page, page_size, status):
        clauses = [WorkflowTask.kind == kind]
        if status:
            clauses.append(WorkflowTask.status == status)
        tasks = db.scalars(select(WorkflowTask).options(defer(WorkflowTask.payload_json)).where(*clauses)
            .order_by(WorkflowTask.created_at.desc(), WorkflowTask.id.desc())
            .offset((page-1)*page_size).limit(page_size))
        return dict(total=db.scalar(select(func.count()).select_from(WorkflowTask).where(*clauses)),
                    page=page, page_size=page_size, items=[view(t) for t in tasks])

    @router.post('/reports', status_code=202)
    def report_create(body: ReportCreate, db=Depends(db_session)):
        from .report_bundle import snapshot, validate_sections
        request = body.model_dump()
        try:
            task = existing(db, 'report', body.request_key, request)
            if task:
                return dict(**view(task), replay=True)
            if any(v <= 0 for v in body.scope.batch_ids) or any(not 1980 <= y <= 2100 for y in body.scope.years):
                raise ValueError('批次编号或年份不合法')
            # SQLite needs an explicit read transaction for a consistent multi-table snapshot.
            connection = db.connection()
            if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql('BEGIN')
            frozen = snapshot(db, body.scope.model_dump())
            sections = [s.model_dump() for s in body.sections]
            validate_sections(frozen, sections)
            task, replay = enqueue(db, 'report', body.request_key, request,
                dict(title=body.title, snapshot=frozen, sections=sections))
            return dict(**view(task), replay=replay)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except OperationalError as exc:
            db.rollback()
            raise HTTPException(409, '报告创建期间数据库繁忙，请沿用原请求编号重试') from exc

    @router.get('/reports')
    def reports(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                status: str | None = Query(None, pattern='^(queued|running|succeeded|failed)$'), db=Depends(db_session)):
        return listing(db, 'report', page, page_size, status)

    @router.get('/reports/{identifier}')
    def report(identifier: str, db=Depends(db_session)):
        return view(get(db, identifier, 'report'))

    @router.post('/reports/{identifier}/retry', status_code=202)
    def report_retry(identifier: str, db=Depends(db_session)):
        try:
            return view(retry(db, get(db, identifier, 'report')))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def download(db, identifier, filename):
        from .report_bundle import artifact_root
        task = get(db, identifier, 'report')
        if task.status != 'succeeded' or not task.result_json:
            raise HTTPException(409, '报告尚未完成，请先查看进度或重试')
        result = json.loads(task.result_json)
        files = {f['name']: f for f in result['files']}
        files['report.zip'] = {'sha256': result['zip_sha256']}
        if filename not in files:
            raise HTTPException(404, '未找到报告文件')
        root = artifact_root().resolve()
        path = (root / result['artifact_directory'] / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(409, '报告文件不可用，请恢复产物目录')
        if hashlib.sha256(path.read_bytes()).hexdigest() != files[filename]['sha256']:
            raise HTTPException(409, '报告文件校验失败，请恢复原始文件')
        media = {'zip': 'application/zip', 'json': 'application/json', 'html': 'text/html',
                 'csv': 'text/csv', 'md': 'text/markdown'}.get(path.suffix[1:], 'text/plain')
        return FileResponse(path, media_type=media,
            filename=f'report-{identifier}.zip' if filename == 'report.zip' else filename,
            headers={'X-Content-SHA256': files[filename]['sha256'], 'Cache-Control': 'no-store'})

    @router.get('/reports/{identifier}/download')
    def report_download(identifier: str, db=Depends(db_session)):
        return download(db, identifier, 'report.zip')

    @router.get('/reports/{identifier}/files/{filename}')
    def report_file(identifier: str, filename: str, db=Depends(db_session)):
        return download(db, identifier, filename)

    @router.get('/handoff-sync')
    def handoff_sync(db=Depends(db_session)):
        from .auto_handoff import reconciliation_view
        return reconciliation_view(db)

    @router.get('/handoffs')
    def handoffs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                 status: str | None = Query(None, pattern='^(queued|running|succeeded|failed)$'), db=Depends(db_session)):
        return listing(db, 'handoff', page, page_size, status)

    @router.get('/handoffs/{identifier}')
    def handoff_task(identifier: str, db=Depends(db_session)):
        return view(get(db, identifier, 'handoff'))

    @router.post('/handoffs/{identifier}/retry', status_code=202)
    def handoff_retry(identifier: str, db=Depends(db_session)):
        try:
            return view(retry(db, get(db, identifier, 'handoff')))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    return router
