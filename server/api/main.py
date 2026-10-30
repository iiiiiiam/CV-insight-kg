from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from server.api.schemas import ImportRequest, LoginRequest
from server.application.a_gateway import AServiceClient, AServiceUnavailable
from server.application.knowledge import KnowledgeSnapshot, UnknownSnapshotPaper
from server.configuration.settings import Settings
from server.domain.auth import AuthService, Session, require_admin, require_admin_write


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
        app.state.knowledge = KnowledgeSnapshot()
        yield
        app.state.auth.sessions.clear()

    app = FastAPI(
        title='CVKG D Gateway',
        version='0.3.0',
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

    async def call_a(method: str, path: str, *, params=None, body=None):
        upstream = await app.state.a_service.request(method, path, params=params, body=body)
        return upstream_response(upstream)

    @app.get('/api/health')
    async def health():
        return {'status': 'ok', 'service': 'd-gateway', 'mode': 'local-single-process'}

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
    async def knowledge_snapshot(_session: Session = Depends(require_admin)):
        return app.state.knowledge.overview()

    @app.get('/api/admin/knowledge/candidates')
    async def knowledge_candidates(paper_id: str = Query(min_length=1, max_length=300),
                                   _session: Session = Depends(require_admin)):
        try:
            return app.state.knowledge.candidates(paper_id)
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

    @app.get('/api/admin/datasets')
    async def list_datasets(_session: Session = Depends(require_admin)):
        return await call_a('GET', '/api/admin/datasets')

    @app.post('/api/admin/imports')
    async def create_import(body: ImportRequest, _session: Session = Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/imports', body=body.model_dump())

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
