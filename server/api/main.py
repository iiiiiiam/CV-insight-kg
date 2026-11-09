import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
import secrets
from typing import Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from server.api.schemas import (ImportRequest, LoginRequest, KnowledgeReviewRequest,
                                GraphImportRequest, GraphPublishRequest, EffectiveGraphSyncRequest,
                                OnlineJobRequest, FileImportRequest, SourceUpdateRequest, ReserveImportRequest)
from server.application.a_gateway import AServiceClient, AServiceUnavailable
from server.application.c_gateway import CServiceClient
from server.application.graph_policy import GraphBoundaryError, require_reviewed_batch
from server.application.graph_batches import prepare_graph_batch
from server.application.knowledge_reading import reading_workspace
from server.application.knowledge import (KnowledgeSnapshot, UnknownSnapshotPaper,
                                          KnowledgeSnapshotInvalid, KnowledgeSnapshotChanged,
                                          KnowledgeReviewRejected, KnowledgeReviewStorageError)
from server.configuration.settings import Settings
from server.domain.auth import AuthService, Session, require_admin, require_admin_write
from server.api.knowledge_feedback import feedback_router
from src.knowledge_builder.feedback import FeedbackConflict


def session_data(session: Session):
    return {
        'authenticated': True,
        'username': session.username,
        'role': 'admin',
        'csrf_token': session.csrf,
        'expires_at': datetime.fromtimestamp(session.expires, timezone.utc).isoformat(),
    }


def upstream_response(upstream):
    content_type = upstream.headers.get('content-type', 'application/json').split(';', 1)[0]
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=content_type)


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.auth = AuthService(settings)
        app.state.a_service = AServiceClient(settings)
        app.state.c_service = CServiceClient(settings)
        app.state.graph_sync_lock = asyncio.Lock()
        app.state.graph_sync_status = {
            'state': 'waiting' if settings.auto_graph_sync else 'disabled',
            'automatic': settings.auto_graph_sync,
            'interval_seconds': settings.graph_sync_interval_seconds,
            'last_attempt_at': None,
            'last_success_at': None,
            'revision': None,
            'batch_id': None,
            'counts': None,
            'error': None,
        }
        task = asyncio.create_task(auto_graph_sync_loop(app)) if settings.auto_graph_sync else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            app.state.auth.sessions.clear()

    app = FastAPI(
        title='CVKG D Gateway',
        version='0.6.0',
        lifespan=lifespan,
        docs_url='/api/docs',
        openapi_url='/api/openapi.json',
        redoc_url=None,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret,
        session_cookie='cvkg_session',
        max_age=settings.ttl,
        same_site='lax',
        https_only=settings.cookie_secure,
    )

    @app.middleware('http')
    async def request_context(request: Request, call_next):
        request.state.request_id = secrets.token_hex(8)
        if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and origin.rstrip('/') not in settings.origins:
                return JSONResponse(status_code=403, content={
                    'error': {'code': 'FORBIDDEN_ORIGIN', 'message': '该请求来源不被允许。'},
                    'request_id': request.state.request_id,
                })
        response = await call_next(request)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if request.url.path.startswith('/api/admin/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={
            'error': {'code': f'HTTP_{exc.status_code}', 'message': str(exc.detail)},
            'request_id': request.state.request_id,
        })

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, _exc: RequestValidationError):
        return JSONResponse(status_code=422, content={
            'error': {'code': 'INVALID_INPUT', 'message': '输入格式不正确，请检查必填项和字段长度。'},
            'request_id': request.state.request_id,
        })

    @app.exception_handler(AServiceUnavailable)
    async def handle_a_unavailable(request: Request, exc: AServiceUnavailable):
        return JSONResponse(status_code=502, content={
            'error': {'code': 'A_SERVICE_UNAVAILABLE', 'message': str(exc)},
            'request_id': request.state.request_id,
        })

    @app.exception_handler(KnowledgeSnapshotInvalid)
    @app.exception_handler(KnowledgeSnapshotChanged)
    async def handle_knowledge_error(request: Request, exc):
        code = 'KNOWLEDGE_SNAPSHOT_CHANGED' if isinstance(exc, KnowledgeSnapshotChanged) else 'KNOWLEDGE_SNAPSHOT_INVALID'
        return JSONResponse(status_code=409, headers={'Cache-Control': 'no-store'}, content={
            'error': {'code': code, 'message': ('已确认知识暂不可用，请管理员检查 B 的数据版本和审核存档。'
                                                if request.url.path == '/api/knowledge/confirmed' else str(exc))},
            'request_id': request.state.request_id,
        })

    @app.exception_handler(KnowledgeReviewRejected)
    @app.exception_handler(KnowledgeReviewStorageError)
    async def handle_review_error(request: Request, exc):
        storage = isinstance(exc, KnowledgeReviewStorageError)
        return JSONResponse(status_code=503 if storage else 422, content={
            'error': {'code': 'KNOWLEDGE_SAVE_FAILED' if storage else 'KNOWLEDGE_REVIEW_REJECTED', 'message': str(exc)},
            'request_id': request.state.request_id,
        })

    def read_knowledge():
        # Fresh and local to this request: invalid archives do not disable login/A APIs.
        return KnowledgeSnapshot(vocabulary_path=settings.b_vocabulary_path,
                                 reviews_directory=settings.b_reviews_directory)

    def read_effective_knowledge(expected_revision: str | None = None):
        """Build B's current public projection once, without writing a file."""
        try:
            return reading_workspace(settings, snapshot_factory=KnowledgeSnapshot).export_effective(
                expected_revision=expected_revision
            )
        except FeedbackConflict as exc:
            raise GraphBoundaryError(409, 'EFFECTIVE_KNOWLEDGE_CHANGED', 'B 的公共知识版本已变化，请刷新后重试同步。') from exc
        except (KnowledgeSnapshotInvalid, OSError, ValueError) as exc:
            raise GraphBoundaryError(503, 'EFFECTIVE_KNOWLEDGE_UNAVAILABLE', '无法读取 B 的有效公共知识，请检查 B 数据和反馈存档。') from exc

    def graph_upstream_error(response, fallback_code, fallback_message):
        try:
            payload = response.json()
            error = payload.get('error', {})
            code = error.get('code') or fallback_code
            message = error.get('message') or fallback_message
        except (ValueError, TypeError, AttributeError):
            code, message = fallback_code, fallback_message
        raise GraphBoundaryError(response.status_code, code, message)

    async def synchronize_effective_graph(app, expected_revision: str | None = None, *, trigger: str):
        """Publish B's current effective projection without a human approval gate."""
        async with app.state.graph_sync_lock:
            status = app.state.graph_sync_status
            status.update(state='running', last_attempt_at=datetime.now(timezone.utc).isoformat(),
                          error=None, trigger=trigger)
            try:
                document = await asyncio.to_thread(read_effective_knowledge, expected_revision)
                revision = document['revision']
                batch_id = 'effective-' + revision
                status.update(revision=revision, batch_id=batch_id, counts=document['counts'])

                metadata_response = await app.state.c_service.batch(batch_id)
                import_replay = True
                if metadata_response.status_code == 404:
                    imported = await app.state.c_service.request(
                        'POST', '/api/admin/graph/effective', body=document,
                        timeout_seconds=settings.c_sync_timeout_seconds,
                    )
                    if not imported.is_success:
                        graph_upstream_error(imported, 'C_EFFECTIVE_IMPORT_FAILED', 'C 无法导入 B 的有效知识快照。')
                    try:
                        import_info = imported.json()
                        if import_info['id'] != batch_id:
                            raise ValueError('batch_id')
                        import_replay = bool(import_info.get('replay'))
                    except (ValueError, KeyError, TypeError) as exc:
                        raise GraphBoundaryError(502, 'C_CONTRACT_INVALID', 'C 有效知识导入响应缺少正确批次标识。') from exc
                    metadata_response = await app.state.c_service.batch(batch_id)
                elif not metadata_response.is_success:
                    graph_upstream_error(metadata_response, 'C_BATCH_CHECK_FAILED', 'C 无法检查有效知识批次。')

                if not metadata_response.is_success:
                    graph_upstream_error(metadata_response, 'C_BATCH_CHECK_FAILED', 'C 导入后无法读取有效知识批次。')
                metadata = require_reviewed_batch(metadata_response.json(), batch_id)
                if not metadata.get('publishable'):
                    raise GraphBoundaryError(409, 'GRAPH_NOT_PUBLISHABLE', 'C 图谱完整性校验未通过，保留当前发布版本。')

                if metadata.get('status') == 'published' and metadata.get('active_batch_id') == batch_id:
                    publication = {'batch_id': batch_id, 'previous_batch_id': batch_id,
                                   'status': 'published', 'unchanged': True}
                else:
                    published = await app.state.c_service.request(
                        'POST', '/api/admin/batches/' + quote(batch_id, safe='') + '/publish',
                        body={'expected_active_batch_id': metadata.get('active_batch_id'),
                              'allow_developer_fixture': False},
                        timeout_seconds=settings.c_sync_timeout_seconds,
                    )
                    if not published.is_success:
                        graph_upstream_error(published, 'C_EFFECTIVE_PUBLISH_FAILED', 'C 无法发布有效知识批次。')
                    publication = published.json()

                result = {'revision': revision, 'batch_id': batch_id,
                          'import_replay': import_replay, 'publication': publication,
                          'counts': document['counts']}
                status.update(state='synced', last_success_at=datetime.now(timezone.utc).isoformat(),
                              error=None, revision=revision, batch_id=batch_id,
                              counts=document['counts'])
                return result
            except GraphBoundaryError as exc:
                status.update(state='error', error={'code': exc.code, 'message': exc.message})
                raise
            except Exception as exc:
                status.update(state='error', error={'code': 'GRAPH_AUTO_SYNC_FAILED',
                                                     'message': '自动图谱同步发生未预期错误。'})
                raise GraphBoundaryError(503, 'GRAPH_AUTO_SYNC_FAILED', '自动图谱同步发生未预期错误，请查看 D 日志。') from exc

    async def auto_graph_sync_loop(app):
        """Retry while D is alive; unchanged revisions are a cheap no-op."""
        while True:
            try:
                await synchronize_effective_graph(app, trigger='automatic')
            except GraphBoundaryError:
                # C/Neo4j may start after D.  Keep the last error for the status
                # page and retry without blocking D's public/B endpoints.
                pass
            await asyncio.sleep(settings.graph_sync_interval_seconds)

    @app.exception_handler(GraphBoundaryError)
    async def handle_graph_error(request: Request, exc: GraphBoundaryError):
        return JSONResponse(status_code=exc.status, content={
            'error': {'code': exc.code, 'message': exc.message},
            'request_id': request.state.request_id,
        })

    @app.get('/api/graph/health')
    async def graph_health():
        return upstream_response(await app.state.c_service.request('GET', '/api/health'))

    @app.get('/api/research/{resource}')
    async def c_research(resource: Literal['papers', 'entities', 'graph'], request: Request):
        response = await app.state.c_service.research('/api/research/' + resource, request.query_params.multi_items())
        return upstream_response(response)

    @app.get('/api/research/{resource}/{entity_id:path}')
    async def c_detail(resource: Literal['papers', 'entities', 'authors', 'institutions'], entity_id: str, request: Request):
        path = '/api/research/' + resource + '/' + quote(entity_id, safe='')
        return upstream_response(await app.state.c_service.research(path, request.query_params.multi_items()))

    @app.get('/api/components/c-paper-detail.js', include_in_schema=False)
    def c_component():
        return FileResponse(Path(__file__).resolve().parents[2] / 'src/graph_query/paper-detail.js', media_type='text/javascript')

    @app.get('/api/admin/graph/preview')
    def graph_preview(batch_id: str = Query(pattern='^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$'),
                      source_batch_id: str = Query(min_length=1, max_length=200),
                      snapshot_revision: str = Query(pattern='^[0-9a-f]{64}$'),
                      _session: Session = Depends(require_admin)):
        _payload, summary = prepare_graph_batch(read_knowledge(), batch_id, source_batch_id, snapshot_revision)
        return summary

    @app.post('/api/admin/graph/import')
    async def graph_import(body: GraphImportRequest, _session: Session = Depends(require_admin_write)):
        payload, summary = prepare_graph_batch(read_knowledge(), body.batch_id, body.source_batch_id, body.snapshot_revision)
        if summary['digest'] != body.digest:
            raise GraphBoundaryError(409, 'GRAPH_PREVIEW_CHANGED', '批次内容与预览不一致，请重新生成预览。')
        return upstream_response(await app.state.c_service.request('POST', '/api/admin/graph/batches', body=payload))

    @app.get('/api/admin/graph/batches/{batch_id}')
    async def graph_batch(batch_id: str, _session: Session = Depends(require_admin)):
        return upstream_response(await app.state.c_service.batch(batch_id))

    @app.post('/api/admin/graph/batches/{batch_id}/publish')
    async def graph_publish(batch_id: str, body: GraphPublishRequest, _session: Session = Depends(require_admin_write)):
        response = await app.state.c_service.batch(batch_id)
        if not response.is_success:
            return upstream_response(response)
        metadata = require_reviewed_batch(response.json(), batch_id)
        if not metadata.get('publishable'):
            raise GraphBoundaryError(409, 'GRAPH_NOT_PUBLISHABLE', '批次完整性校验未通过，保留当前发布版本。')
        path = '/api/admin/batches/' + quote(batch_id, safe='') + '/publish'
        return upstream_response(await app.state.c_service.request('POST', path,
            body={'expected_active_batch_id': body.expected_active_batch_id, 'allow_developer_fixture': False}))

    @app.get('/api/admin/graph/effective')
    def effective_graph_preview(expected_revision: str | None = Query(default=None, pattern='^[0-9a-f]{64}$'),
                                _session: Session = Depends(require_admin)):
        """Show the exact B snapshot that a subsequent sync will import."""
        document = read_effective_knowledge(expected_revision)
        revision = document['revision']
        return {
            'format_version': document['format_version'],
            'publication_policy': document['publication_policy'],
            'revision': revision,
            'batch_id': 'effective-' + revision,
            'source_batch_id': 'B-effective:' + revision,
            'counts': document['counts'],
            'generated_at': document['generated_at'],
            'sync_status': dict(app.state.graph_sync_status),
        }

    @app.get('/api/admin/graph/effective/status')
    def effective_graph_status(_session: Session = Depends(require_admin)):
        """Lightweight status read; automatic sync itself does not require login."""
        return dict(app.state.graph_sync_status)

    @app.post('/api/admin/graph/effective/sync')
    async def effective_graph_sync(body: EffectiveGraphSyncRequest,
                                   _session: Session = Depends(require_admin_write)):
        """Retry immediately; normal B-to-C publication is automatic.

        B remains the source of truth.  If C is unavailable, B's feedback
        operation is still preserved and this endpoint returns an explicit
        retryable error rather than silently serving stale graph data.
        """
        return await synchronize_effective_graph(app, body.expected_revision, trigger='manual_retry')

    async def call_a(method: str, path: str, *, params=None, body=None):
        upstream = await app.state.a_service.request(method, path, params=params, body=body)
        return upstream_response(upstream)

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'service': 'd-gateway', 'mode': 'local-single-process',
                'graph_sync': dict(app.state.graph_sync_status)}

    @app.post('/api/admin/sessions')
    async def login(body: LoginRequest, request: Request):
        return session_data(app.state.auth.login(request, body.username, body.password))

    @app.get('/api/admin/session')
    async def current(session: Session = Depends(require_admin)):
        return session_data(session)

    @app.delete('/api/admin/session', status_code=204)
    async def logout(request: Request, _session: Session = Depends(require_admin_write)):
        app.state.auth.logout(request)
        return Response(status_code=204)

    @app.get('/api/admin/probe')
    async def read_probe(session: Session = Depends(require_admin)):
        return {'ok': True, 'username': session.username, 'message': '受保护接口访问成功。', 'data_changed': False}

    @app.post('/api/admin/probe')
    async def write_probe(session: Session = Depends(require_admin_write)):
        return {
            'ok': True,
            'username': session.username,
            'message': '管理员权限及 CSRF 校验通过；未执行数据导入。',
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'data_changed': False,
        }

    @app.get('/api/papers')
    async def list_papers(request: Request):
        return await call_a('GET', '/api/papers', params=dict(request.query_params))

    @app.get('/api/papers/{paper_id}')
    async def get_paper(paper_id: int):
        return await call_a('GET', f'/api/papers/{paper_id}')

    @app.get('/api/papers/{paper_id}/graph')
    async def paper_metadata_graph(paper_id: int):
        # Forward A's actual Paper--PUBLISHED_IN-->Venue relation, never synthesize C data.
        return await call_a('GET', f'/api/papers/{paper_id}/graph')

    @app.get('/api/admin/knowledge/snapshot')
    def knowledge_snapshot(_session: Session = Depends(require_admin)):
        return read_knowledge().overview()

    @app.get('/api/admin/knowledge/candidates')
    def knowledge_candidates(paper_id: str = Query(min_length=1, max_length=300),
                             snapshot_revision: str | None = Query(default=None, pattern='^[0-9a-f]{64}$'),
                             _session: Session = Depends(require_admin)):
        try:
            return read_knowledge().candidates(paper_id, snapshot_revision)
        except UnknownSnapshotPaper as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/admin/export')
    async def export_papers(request: Request, _session: Session = Depends(require_admin)):
        upstream = await app.state.a_service.request('GET', '/api/admin/export', params=dict(request.query_params))
        response = upstream_response(upstream)
        for name in ('content-disposition', 'x-paper-count'):
            if name in upstream.headers:
                response.headers[name] = upstream.headers[name]
        return response

    @app.post('/api/admin/knowledge/reviews')
    def review_knowledge(body: KnowledgeReviewRequest, session: Session = Depends(require_admin_write)):
        try:
            return read_knowledge().apply_review(body.paper_id, body.candidate_id, body.action,
                                                reviewer=session.username, reason=body.reason,
                                                snapshot_revision=body.snapshot_revision, name=body.name)
        except UnknownSnapshotPaper as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get('/api/admin/knowledge/exports/{filename}')
    def download_knowledge(filename: Literal['confirmed.json', 'pending.json', 'rejected.json', 'bundle.zip'],
                           snapshot_revision: str = Query(pattern='^[0-9a-f]{64}$'),
                           _session: Session = Depends(require_admin)):
        body, media_type, name = read_knowledge().download(filename, snapshot_revision)
        return Response(content=body, media_type=media_type,
                        headers={'Content-Disposition': f'attachment; filename="{name}"'})

    @app.get('/api/knowledge/confirmed')
    def confirmed_knowledge(paper_id: str = Query(min_length=1, max_length=300)):
        return JSONResponse(content=read_knowledge().confirmed(paper_id), headers={'Cache-Control': 'no-store'})

    @app.get('/api/admin/datasets')
    async def list_datasets(_session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/datasets')

    @app.get('/api/admin/data-overview')
    async def data_overview(request: Request, _session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/data-overview', params=dict(request.query_params))

    @app.get('/api/admin/new-papers')
    async def new_papers(request: Request, _session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/new-papers', params=dict(request.query_params))

    @app.get('/api/admin/batch-comparison')
    async def batch_comparison(request: Request, _session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/batch-comparison', params=dict(request.query_params))

    @app.get('/api/admin/handoff')
    async def handoff_data(request: Request, _session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/handoff', params=dict(request.query_params))

    @app.post('/api/admin/imports')
    async def create_import(body: ImportRequest, _session: Session = Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/imports', body=body.model_dump())

    @app.get('/api/admin/reserve')
    async def reserve_library(_session: Session = Depends(require_admin)):
        return await call_a('GET','/api/admin/reserve')

    @app.post('/api/admin/reserve/imports')
    async def import_reserve(body: ReserveImportRequest,_session: Session = Depends(require_admin_write)):
        return await call_a('POST','/api/admin/reserve/imports',body=body.model_dump())

    @app.post('/api/admin/file-imports')
    async def import_file(body: FileImportRequest, _session: Session = Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/file-imports', body=body.model_dump())

    @app.get('/api/admin/sources')
    async def get_sources(_session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/sources')

    @app.put('/api/admin/sources/{name}')
    async def update_source(name: str, body: SourceUpdateRequest, _session: Session = Depends(require_admin_write)):
        return await call_a('PUT', '/api/admin/sources/' + quote(name, safe=''), body=body.model_dump())

    @app.post('/api/admin/jobs')
    async def create_online_job(body: OnlineJobRequest, _session: Session = Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/jobs', body=body.model_dump())

    @app.get('/api/admin/jobs')
    async def list_jobs(_session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/jobs')

    @app.get('/api/admin/jobs/{job_id}')
    async def get_job(job_id: int, _session: Session = Depends(require_admin)):
        return await call_a('GET', f'/api/admin/jobs/{job_id}')

    @app.get('/api/admin/jobs/{job_id}/papers')
    async def get_job_papers(job_id: int, request: Request, _session: Session = Depends(require_admin)):
        return await call_a('GET', f'/api/admin/jobs/{job_id}/papers', params=dict(request.query_params))

    @app.post('/api/admin/jobs/{job_id}/retry')
    async def retry_job(job_id: int, _session: Session = Depends(require_admin_write)):
        return await call_a('POST', f'/api/admin/jobs/{job_id}/retry')

    app.include_router(feedback_router(settings))

    dist = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
    if (dist / 'index.html').is_file():
        if (dist / 'assets').is_dir():
            app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

        @app.get('/{path:path}', include_in_schema=False)
        async def frontend(path: str):
            if path == 'api' or path.startswith('api/'):
                raise HTTPException(404, '接口不存在。')
            return FileResponse(dist / 'index.html')

    return app
