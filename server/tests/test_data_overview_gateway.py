import httpx
import pytest
from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.a_gateway import AServiceClient
from server.configuration.settings import Settings


@pytest.fixture
def client():
    settings = Settings(username='admin', password='UnitTest-Password-2026!', secret='gateway-test-' * 5)
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.mark.parametrize(('path', 'upstream'), [
    ('/api/admin/data-overview?days=14', '/api/admin/data-overview'),
    ('/api/admin/new-papers?day=2026-11-03&page=2', '/api/admin/new-papers'),
    ('/api/admin/batch-comparison?first=1&second=2', '/api/admin/batch-comparison'),
    ('/api/admin/handoff?batch_id=1', '/api/admin/handoff'),
    ('/api/admin/reserve', '/api/admin/reserve'),
])
def test_data_routes_require_login_and_preserve_response(client, monkeypatch, path, upstream):
    calls = []
    async def request(_self, method, route, **kwargs):
        calls.append((method, route, kwargs.get('params')))
        return httpx.Response(200, json={'value': 20})
    monkeypatch.setattr(AServiceClient, 'request', request)
    assert client.get(path).status_code == 401
    client.post('/api/admin/sessions', json={'username': 'admin', 'password': 'UnitTest-Password-2026!'})
    response = client.get(path)
    assert response.status_code == 200 and response.json() == {'value': 20}
    assert calls[0][0:2] == ('GET', upstream)
    assert (calls[0][2] or {}) == dict(httpx.URL('http://local' + path).params)


def test_online_job_requires_csrf_and_forwards_options(client, monkeypatch):
    calls = []
    async def request(_self, method, route, **kwargs):
        calls.append((method, route, kwargs.get('body')))
        return httpx.Response(201, json={'id': 12})
    monkeypatch.setattr(AServiceClient, 'request', request)
    payload = {'venue': 'CVPR', 'year': 2024, 'source': 'cvf', 'start': 2, 'count': 3}
    assert client.post('/api/admin/jobs', json=payload).status_code == 401
    login = client.post('/api/admin/sessions', json={'username': 'admin', 'password': 'UnitTest-Password-2026!'}).json()
    assert client.post('/api/admin/jobs', json=payload).status_code == 403
    headers = {'X-CSRF-Token': login['csrf_token']}
    assert client.post('/api/admin/jobs', json={**payload, 'count': 101}, headers=headers).status_code == 422
    response = client.post('/api/admin/jobs', json=payload, headers=headers)
    assert response.status_code == 201 and response.json()['id'] == 12
    assert calls == [('POST', '/api/admin/jobs', payload)]


@pytest.mark.parametrize(('method','path','payload'), [
    ('POST','/api/admin/reserve/imports',{'venue':'ICCV','year':2023,'source':'openalex','count':20}),
    ('POST','/api/admin/file-imports',{'content':'{}\n','manifest':{'source':'openalex'}}),
    ('PUT','/api/admin/sources/openalex',{'enabled':False,'page_size':50,'max_retries':2}),
])
def test_a_write_routes_preserve_auth_and_payload(client,monkeypatch,method,path,payload):
    calls=[]
    async def request(_self,verb,route,**kwargs):
        calls.append((verb,route,kwargs.get('body')))
        return httpx.Response(201 if verb=='POST' else 200,json={'ok':True})
    monkeypatch.setattr(AServiceClient,'request',request)
    assert client.request(method,path,json=payload).status_code==401
    login=client.post('/api/admin/sessions',json={'username':'admin','password':'UnitTest-Password-2026!'}).json()
    assert client.request(method,path,json=payload).status_code==403
    response=client.request(method,path,json=payload,headers={'X-CSRF-Token':login['csrf_token']})
    assert response.status_code in (200,201)
    assert calls==[(method,path,payload)]
