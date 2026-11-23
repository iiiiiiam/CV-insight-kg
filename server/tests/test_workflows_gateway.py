from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.a_gateway import AServiceClient
from server.application.c_gateway import CServiceClient
from server.configuration.settings import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(username='admin', password='Workflow-Test-Password!', secret='workflow-secret-'*4,
                        auto_graph_sync=False, user_store=str(tmp_path/'users.json'),
                        b_batch_registry=str(tmp_path/'ledger.json'), b_source_offline=True)
    with TestClient(create_app(settings)) as client:
        yield client


def login(client):
    result = client.post('/api/admin/sessions', json={'username': 'admin', 'password': 'Workflow-Test-Password!'})
    assert result.status_code == 200
    return {'X-CSRF-Token': result.json()['csrf_token']}


def test_report_and_delivery_write_routes_require_admin_csrf(client, monkeypatch):
    async def request(*args, **kwargs):
        raise AssertionError('Unauthorized call reached A')
    monkeypatch.setattr(AServiceClient, 'request', request)
    assert client.get('/api/admin/reports').status_code == 401
    login(client)
    for route in ('reports', 'handoffs'):
        assert client.post('/api/admin/'+route, json={}).status_code == 403
        assert client.post('/api/admin/'+route+'/unknown/retry').status_code == 403


def test_creation_validation_and_report_download_preserve_attachment_and_checksum(client, monkeypatch):
    async def request(_self, method, path, **kwargs):
        if path.endswith('/download'):
            return httpx.Response(200, content=b'zip-fixture', headers={'Content-Type': 'application/zip',
                'Content-Disposition': 'attachment; filename="report.zip"', 'X-Content-SHA256': 'fixture-sha'})
        assert (method, path) == ('POST', '/api/admin/reports')
        assert kwargs['body']['request_key'] == 'one'
        return httpx.Response(202, json={'id': 'one', 'status': 'queued'})
    monkeypatch.setattr(AServiceClient, 'request', request)
    headers = login(client)
    assert client.post('/api/admin/reports', headers=headers, json={'scope': {'venues': ['UNKNOWN']}}).status_code == 422
    created = client.post('/api/admin/reports', headers=headers, json={'request_key': 'one'})
    assert created.status_code == 202 and created.json()['status'] == 'queued'
    download = client.get('/api/admin/reports/one/download')
    assert download.headers['content-disposition'] == 'attachment; filename="report.zip"'
    assert download.headers['x-content-sha256'] == 'fixture-sha'
    assert download.content == b'zip-fixture'


def test_native_b_and_c_report_inputs_pin_same_revision(client, monkeypatch):
    revision = 'a'*64
    document = dict(revision=revision, counts={'papers': 1}, papers=[{'input': {'openalex_id': 'W1'}}])
    class Workspace:
        def export_effective(self, expected_revision=None):
            assert expected_revision in (None, revision)
            return document
    monkeypatch.setattr('server.api.main.reading_workspace', lambda *a, **k: Workspace())
    monkeypatch.setattr('server.api.workflows.read_b_report', lambda *a: {
        'scope': {'knowledge_revision': revision, 'paper_ids': ['W1']}, 'knowledge': document})
    async def batch(_self, identifier):
        assert identifier == 'effective-'+revision
        return httpx.Response(200, json={'provenance': 'effective_export', 'source_revision': revision})
    async def statistics(_self, method, path, **kwargs):
        assert (method, path) == ('GET', '/api/research/report-statistics')
        assert kwargs['params'] == {'batch_id': 'effective-'+revision,
                                    'expected_revision': revision, 'limit': 30}
        return httpx.Response(200, json={
            'provider': 'C', 'revision': revision, 'paper_ids': ['W1'],
            'data': {'format_version': 'c-report-statistics/1',
                     'batch_id': 'effective-'+revision, 'revision': revision,
                     'statistics': {'batch_id': 'effective-'+revision, 'paper_count': 1},
                     'available_sections': ['statistics'], 'pending_sections': ['dual_trends']}})
    monkeypatch.setattr(CServiceClient, 'batch', batch)
    monkeypatch.setattr(CServiceClient, 'request', statistics)
    login(client)
    b = client.get('/api/admin/report-inputs/B').json()
    c = client.get('/api/admin/report-inputs/C?expected_revision='+revision).json()
    assert b['paper_ids'] == c['paper_ids'] == ['W1']
    assert b['revision'] == c['revision'] == revision
    assert 'dual_trends' in c['data']['pending_sections']


def test_publication_status_proxy_is_admin_only_and_preserves_history(client, monkeypatch):
    async def request(_self, method, path, **kwargs):
        assert (method, path) == ('GET', '/api/admin/graph/publication-status')
        assert kwargs['params'] == {'page': 2, 'page_size': 5}
        return httpx.Response(200, json={'active_batch_id': 'effective-current',
            'active': {'id': 'effective-current'}, 'publish_generation': 4,
            'items': [{'id': 'effective-current'}], 'total': 1, 'page': 2, 'page_size': 5})
    monkeypatch.setattr(CServiceClient, 'request', request)
    assert client.get('/api/admin/graph/publication-status?page=2&page_size=5').status_code == 401
    login(client)
    result = client.get('/api/admin/graph/publication-status?page=2&page_size=5')
    assert result.status_code == 200
    assert result.json()['publish_generation'] == 4


def test_effective_sync_uses_active_batch_and_generation_cas(client, monkeypatch):
    revision = 'c'*64
    document = {'revision': revision, 'counts': {'papers': 1, 'entities': 2, 'relations': 1}}
    class Workspace:
        def export_effective(self, expected_revision=None):
            assert expected_revision == revision
            return document
    monkeypatch.setattr('server.api.main.reading_workspace', lambda *a, **k: Workspace())
    async def batch(_self, identifier):
        assert identifier == 'effective-'+revision
        return httpx.Response(200, json={'id': identifier, 'provenance': 'effective_export',
            'source_revision': revision, 'publishable': True})
    async def request(_self, method, path, **kwargs):
        if path == '/api/admin/graph/publication-status':
            return httpx.Response(200, json={'active_batch_id': 'effective-old',
                'active': {'id': 'effective-old', 'source_revision': 'd'*64},
                'publish_generation': 9, 'items': [], 'total': 1, 'page': 1, 'page_size': 1})
        assert (method, path) == ('POST', '/api/admin/batches/effective-'+revision+'/publish')
        assert kwargs['body'] == {'expected_active_batch_id': 'effective-old',
                                  'expected_publish_generation': 9,
                                  'allow_developer_fixture': False}
        return httpx.Response(200, json={'batch_id': 'effective-'+revision,
            'previous_batch_id': 'effective-old', 'status': 'published',
            'unchanged': False, 'publish_generation': 10})
    monkeypatch.setattr(CServiceClient, 'batch', batch)
    monkeypatch.setattr(CServiceClient, 'request', request)
    headers = login(client)
    result = client.post('/api/admin/graph/effective/sync', headers=headers,
                         json={'expected_revision': revision})
    assert result.status_code == 200, result.text
    assert result.json()['publication']['publish_generation'] == 10


def test_c_report_input_rejects_other_revision(client, monkeypatch):
    revision = 'a'*64
    monkeypatch.setattr('server.api.main.reading_workspace', lambda *a, **k:
        SimpleNamespace(export_effective=lambda **k: {'revision': revision}))
    async def batch(*args):
        return httpx.Response(200, json={'provenance': 'effective_export', 'source_revision': 'b'*64})
    monkeypatch.setattr(CServiceClient, 'batch', batch)
    login(client)
    assert client.get('/api/admin/report-inputs/C?expected_revision='+revision).status_code == 409


def test_pipeline_detects_a_changed_since_delivery(client, monkeypatch):
    async def request(_self, method, path, **kwargs):
        if path.endswith('/handoffs/task'):
            return httpx.Response(200, json={'batch_id': 1, 'batch_revision': 'a'*64,
                'status': 'succeeded', 'stage': 'completed', 'result': {}})
        return httpx.Response(200, json={'batch_revision': 'b'*64})
    monkeypatch.setattr(AServiceClient, 'request', request)
    login(client)
    result = client.get('/api/admin/handoffs/task/pipeline').json()
    assert result['stages']['A']['status'] == 'changed'
    assert result['stages']['C']['status'] == 'waiting'


@pytest.mark.parametrize('c_status,expected', [(200, 'succeeded'), (503, 'unavailable'), (404, 'waiting')])
def test_pipeline_reads_actual_b_and_c_status(client, monkeypatch, c_status, expected):
    revision = 'a'*64
    async def request(_self, method, path, **kwargs):
        if path.endswith('/handoffs/task'):
            return httpx.Response(200, json={'batch_id': 1, 'batch_revision': revision,
                'status': 'succeeded', 'stage': 'completed', 'result': {'b_snapshot_revision': 'input-revision'}})
        return httpx.Response(200, json={'batch_revision': revision})
    monkeypatch.setattr(AServiceClient, 'request', request)
    async def readiness(*args):
        return {'input_snapshot_revision': 'input-revision', 'knowledge_revision': revision,
                'source_enrichment': {'state': 'complete', 'pending': 0},
                'results': {'available': True, 'empty': False}}
    monkeypatch.setattr('server.api.workflows.read_b_readiness', readiness)
    async def metadata(*args):
        return httpx.Response(c_status, json={'source_revision': revision, 'status': 'published',
            'provenance': 'effective_export', 'publishable': True,
            'id': 'effective-'+revision, 'active_batch_id': 'effective-'+revision})
    monkeypatch.setattr(CServiceClient, 'batch', metadata)
    login(client)
    stages = client.get('/api/admin/handoffs/task/pipeline').json()['stages']
    assert stages['B']['status'] == 'succeeded'
    assert stages['C']['status'] == expected


def test_new_b_report_input_is_complete_and_version_pinned(client):
    assert client.get('/api/admin/report-inputs/B').status_code == 401
    login(client)
    response = client.get('/api/admin/report-inputs/B')
    assert response.status_code == 200, response.text
    section = response.json()
    assert section['data']['format_version'] == 'knowledge-report/1'
    assert section['revision'] == section['data']['scope']['knowledge_revision']
    assert section['paper_ids'] == section['data']['scope']['paper_ids']
    assert section['data']['quality']['accuracy']['precision'] is None
    assert 'author_tags' in section['data']
    assert client.get('/api/admin/report-inputs/B?expected_revision='+'0'*64).status_code == 409


@pytest.mark.parametrize('state', ['pending', 'partial', 'interrupted', 'running'])
def test_pipeline_readable_results_are_distinct_from_source_completion(client, monkeypatch, state):
    revision = 'b'*64
    async def request(_self, method, path, **kwargs):
        if path.endswith('/handoffs/task'):
            return httpx.Response(200, json={'batch_id': 1, 'batch_revision': revision,
                'status': 'succeeded', 'stage': 'completed', 'result': {'b_snapshot_revision': 'input'}})
        return httpx.Response(200, json={'batch_revision': revision})
    async def readiness(*args):
        return {'input_snapshot_revision': 'input', 'knowledge_revision': revision,
                'source_enrichment': {'state': state}, 'results': {'available': True, 'empty': False}}
    async def metadata(*args):
        return httpx.Response(404, json={})
    monkeypatch.setattr(AServiceClient, 'request', request)
    monkeypatch.setattr('server.api.workflows.read_b_readiness', readiness)
    monkeypatch.setattr(CServiceClient, 'batch', metadata)
    login(client)
    stages = client.get('/api/admin/handoffs/task/pipeline').json()['stages']
    assert stages['B']['status'] == 'succeeded'
    assert stages['B']['source_enrichment']['state'] == state
    assert stages['C']['status'] == 'waiting'
