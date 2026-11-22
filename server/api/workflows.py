"""Thin D-compatible routes for A tasks; public navigation remains D-owned."""
import asyncio
import httpx

from fastapi import Depends, HTTPException, Query, Request, Response

from app.workflow_api import HandoffCreate, ReportCreate
from app.formal_api import FormalInput
from server.domain.auth import require_admin, require_admin_write


def read_b_report(settings, expected_revision):
    from server.application.knowledge_reading import reading_report
    from server.application.knowledge import KnowledgeSnapshotInvalid
    from src.knowledge_builder.feedback import FeedbackConflict
    try:
        return reading_report(settings, expected_revision=expected_revision)
    except FeedbackConflict as exc:
        raise HTTPException(409, 'B 知识版本已变化，请重新获取报告数据') from exc
    except (KnowledgeSnapshotInvalid, OSError, ValueError) as exc:
        raise HTTPException(503, 'B 报告知识附件暂不可读，请检查存档后重试') from exc


async def read_b_readiness(app, request):
    # Reuse B's authenticated API, including its version double-checks and
    # running/interrupted state. ASGI transport keeps this call within the app.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://b.internal', cookies=request.cookies) as client:
        result = await client.get('/api/admin/knowledge/batches/readiness')
    if not result.is_success:
        raise HTTPException(result.status_code, 'B 当前处理状态暂不可读')
    return result.json()


def register_workflows(app, call_a, read_effective):
    @app.post('/api/admin/formal/batches', status_code=201)
    async def formal_import(body: FormalInput, _session=Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/formal/batches', body=body.model_dump())

    @app.get('/api/admin/formal/batches')
    async def formal_batches(request: Request, _session=Depends(require_admin)):
        return await call_a('GET', '/api/admin/formal/batches', params=list(request.query_params.multi_items()))

    @app.post('/api/admin/reports', status_code=202)
    async def create_report(body: ReportCreate, _session=Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/reports', body=body.model_dump())

    @app.get('/api/admin/reports')
    async def reports(request: Request, _session=Depends(require_admin)):
        return await call_a('GET', '/api/admin/reports', params=list(request.query_params.multi_items()))

    @app.get('/api/admin/reports/{identifier}')
    async def report(identifier: str, _session=Depends(require_admin)):
        return await call_a('GET', f'/api/admin/reports/{identifier}')

    @app.post('/api/admin/reports/{identifier}/retry', status_code=202)
    async def retry_report(identifier: str, _session=Depends(require_admin_write)):
        return await call_a('POST', f'/api/admin/reports/{identifier}/retry')

    async def download(path):
        result = await app.state.a_service.request('GET', path)
        headers = {k: v for k, v in result.headers.items() if k.lower() in
                   ('content-type', 'content-disposition', 'x-content-sha256', 'cache-control')}
        return Response(result.content, status_code=result.status_code, headers=headers)

    @app.get('/api/admin/reports/{identifier}/download')
    async def report_download(identifier: str, _session=Depends(require_admin)):
        return await download(f'/api/admin/reports/{identifier}/download')

    @app.get('/api/admin/reports/{identifier}/files/{filename}')
    async def report_file(identifier: str, filename: str, _session=Depends(require_admin)):
        from urllib.parse import quote
        return await download(f'/api/admin/reports/{identifier}/files/{quote(filename, safe="")}')

    @app.post('/api/admin/handoffs', status_code=202)
    async def handoff(body: HandoffCreate, _session=Depends(require_admin_write)):
        return await call_a('POST', '/api/admin/handoffs', body=body.model_dump())

    @app.get('/api/admin/handoffs')
    async def handoffs(request: Request, _session=Depends(require_admin)):
        return await call_a('GET', '/api/admin/handoffs', params=list(request.query_params.multi_items()))

    @app.get('/api/admin/handoffs/{identifier}')
    async def handoff_task(identifier: str, _session=Depends(require_admin)):
        return await call_a('GET', f'/api/admin/handoffs/{identifier}')

    @app.post('/api/admin/handoffs/{identifier}/retry', status_code=202)
    async def retry_handoff(identifier: str, _session=Depends(require_admin_write)):
        return await call_a('POST', f'/api/admin/handoffs/{identifier}/retry')

    @app.get('/api/admin/report-inputs/B')
    def b_report_input(expected_revision: str | None = Query(None, pattern='^[0-9a-f]{64}$'),
                       _session=Depends(require_admin)):
        document = read_b_report(app.state.auth.settings, expected_revision)
        return dict(provider='B', revision=document['scope']['knowledge_revision'],
                    paper_ids=document['scope']['paper_ids'], data=document)

    @app.get('/api/admin/report-inputs/C')
    async def c_report_input(expected_revision: str = Query(pattern='^[0-9a-f]{64}$'),
                             _session=Depends(require_admin)):
        # Use the exact B-derived graph batch; never mix current B and arbitrary active C.
        document = await asyncio.to_thread(read_effective, expected_revision)
        batch_id = 'effective-' + expected_revision
        metadata = await app.state.c_service.batch(batch_id)
        if not metadata.is_success:
            raise HTTPException(metadata.status_code, 'C 尚未提供对应版本的发布数据')
        meta = metadata.json()
        if meta.get('provenance') != 'effective_export' or meta.get('source_revision') != expected_revision:
            raise HTTPException(409, 'C 的数据来源或版本与 B 不一致')
        result = await app.state.c_service.request('GET', '/api/research/statistics', params={'batch_id': batch_id})
        if not result.is_success:
            raise HTTPException(result.status_code, 'C 统计读取失败，可稍后重试')
        data = result.json()
        if data.get('paper_count') != document['counts']['papers'] or data.get('batch_id') != batch_id:
            raise HTTPException(409, 'C 统计范围与本次知识快照不一致')
        return dict(provider='C', revision=expected_revision,
                    paper_ids=[p['input']['openalex_id'] for p in document['papers']],
                    data={'batch_id': batch_id, 'statistics': data,
                          'available_sections': ['years', 'distributions'],
                          'pending_sections': ['dual_trends', 'coauthors', 'author_statistics', 'institution_statistics']})

    @app.get('/api/admin/handoffs/{identifier}/pipeline')
    async def pipeline(identifier: str, request: Request, _session=Depends(require_admin)):
        task = await call_a('GET', f'/api/admin/handoffs/{identifier}')
        # call_a returns an HTTP Response, so preserve upstream failures unchanged.
        import json
        if task.status_code != 200:
            return task
        value = json.loads(task.body)
        stages = {'A': {'status': 'succeeded', 'message': 'A 批次已完成，交接版本已固定'},
                  'B': {'status': value['status'], 'message': '交接任务：' + value['stage']},
                  'C': {'status': 'waiting', 'message': '等待对应知识版本发布'}}
        current = await call_a('GET', '/api/admin/handoff', params={'batch_id': str(value['batch_id'])})
        if current.status_code != 200:
            return current
        if json.loads(current.body).get('batch_revision') != value['batch_revision']:
            stages['A'] = {'status': 'changed', 'message': 'A 批次已变化，需要交接新的批次版本'}
            stages['B'] = {'status': 'waiting', 'message': '等待新版本交接'}
            return dict(task_id=identifier, stages=stages)
        if value['status'] != 'succeeded':
            return dict(task_id=identifier, stages=stages, error=value.get('error'))
        try:
            readiness = await read_b_readiness(app, request)
            if readiness['input_snapshot_revision'] != value['result']['b_snapshot_revision']:
                stages['B'] = {'status': 'changed', 'message': 'B 输入已变化，请按新版本核对'}
                return dict(task_id=identifier, stages=stages)
            summary = readiness['source_enrichment']
            available = readiness['results']['available']
            stages['B'] = {'status': 'succeeded' if available else 'processing',
                           'message': '可读取 B 当前有效知识' if available else 'B 正在处理知识结果',
                           'revision': readiness['knowledge_revision'], 'source_enrichment': summary,
                           'results': readiness['results']}
            if not available:
                return dict(task_id=identifier, stages=stages)
            document = {'revision': readiness['knowledge_revision']}
        except HTTPException as exc:
            stages['B'] = {'status': 'changed' if exc.status_code == 409 else 'unavailable',
                           'message': 'B 状态已变化，请刷新核对' if exc.status_code == 409 else '暂无法核对 B 知识，可刷新重试'}
            return dict(task_id=identifier, stages=stages)
        except Exception:
            stages['B'] = {'status': 'unavailable', 'message': '暂无法核对 B 知识，可刷新重试'}
            return dict(task_id=identifier, stages=stages)
        try:
            metadata = await app.state.c_service.batch('effective-' + document['revision'])
            if metadata.is_success:
                meta = metadata.json()
                if (meta.get('source_revision') == document['revision'] and meta.get('status') == 'published'
                    and meta.get('provenance') == 'effective_export' and meta.get('publishable')
                    and meta.get('active_batch_id') == meta.get('batch_id', meta.get('id'))):
                    stages['C'] = {'status': 'succeeded', 'message': '对应知识版本已发布',
                                   'batch_id': 'effective-' + document['revision']}
            elif metadata.status_code >= 500:
                stages['C'] = {'status': 'unavailable', 'message': '发布服务暂不可用，可刷新重试'}
        except Exception:
            stages['C'] = {'status': 'unavailable', 'message': '暂无法核对发布服务，可刷新重试'}
        return dict(task_id=identifier, stages=stages)
