import httpx
import pytest
from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.a_gateway import AServiceClient, AServiceUnavailable
from server.configuration.settings import Settings


@pytest.fixture
def client():
    settings = Settings(username='admin', password='UnitTest-Password-2026!', secret='gateway-test-' * 5)
    with TestClient(create_app(settings)) as value:
        yield value


def test_real_paper_metadata_graph_is_forwarded_unchanged(client, monkeypatch):
    body = {'basis': 'paper_metadata', 'nodes': [
        {'id': 'paper:1', 'type': 'Paper', 'paper_id': 1, 'label': 'Fixture'},
        {'id': 'venue:CVPR', 'type': 'Venue', 'label': 'CVPR'}],
        'edges': [{'source': 'paper:1', 'target': 'venue:CVPR', 'type': 'PUBLISHED_IN'}]}

    async def request(_self, method, path, **_kwargs):
        assert (method, path) == ('GET', '/api/papers/1/graph')
        return httpx.Response(200, json=body)

    monkeypatch.setattr(AServiceClient, 'request', request)
    assert client.get('/api/papers/1/graph').json() == body


def test_upstream_unavailable_never_returns_fallback_papers(client, monkeypatch):
    async def request(*_args, **_kwargs):
        raise AServiceUnavailable('无法连接 A 数据服务')

    monkeypatch.setattr(AServiceClient, 'request', request)
    response = client.get('/api/papers')
    assert response.status_code == 502
    assert response.json()['error']['code'] == 'A_SERVICE_UNAVAILABLE'
    assert 'items' not in response.json()


def test_upstream_not_found_is_preserved(client, monkeypatch):
    async def request(*_args, **_kwargs):
        return httpx.Response(404, json={'detail': 'Paper not found'})

    monkeypatch.setattr(AServiceClient, 'request', request)
    assert client.get('/api/papers/999999').status_code == 404


def test_malformed_import_is_rejected_without_calling_a(client, monkeypatch):
    async def request(*_args, **_kwargs):
        raise AssertionError('Malformed request must not reach A')

    monkeypatch.setattr(AServiceClient, 'request', request)
    session = client.post('/api/admin/sessions', json={'username': 'admin', 'password': 'UnitTest-Password-2026!'}).json()
    headers = {'X-CSRF-Token': session['csrf_token'], 'Content-Type': 'application/json'}
    assert client.post('/api/admin/imports', content='{broken', headers=headers).status_code == 422
    assert client.post('/api/admin/imports', json={}, headers=headers).status_code == 422


def test_export_is_protected_and_preserves_csv_headers(client, monkeypatch):
    async def request(_self, method, path, **kwargs):
        assert (method, path) == ('GET', '/api/admin/export')
        assert kwargs['params']['batch_id'] == '1'
        return httpx.Response(200, text='paper_id,title\r\n1,Fixture\r\n', headers={
            'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': 'attachment; filename="papers.csv"', 'X-Paper-Count': '1'})

    monkeypatch.setattr(AServiceClient, 'request', request)
    assert client.get('/api/admin/export').status_code == 401
    client.post('/api/admin/sessions', json={'username': 'admin', 'password': 'UnitTest-Password-2026!'})
    response = client.get('/api/admin/export?batch_id=1')
    assert response.status_code == 200
    assert response.headers['x-paper-count'] == '1'
    assert response.headers['content-disposition'] == 'attachment; filename="papers.csv"'


@pytest.mark.anyio
async def test_a_token_is_sent_by_server_only(monkeypatch):
    settings = Settings(username='admin', password='not-used-here', secret='not-used-here', a_admin_token='test-a-token')

    def handle(request):
        assert request.headers['authorization'] == 'Bearer test-a-token'
        assert request.url.path == '/api/admin/datasets'
        return httpx.Response(200, json={'items': []})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    response = await AServiceClient(settings).request('GET', '/api/admin/datasets')
    assert response.json() == {'items': []}
