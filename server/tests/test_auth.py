import time
import pytest
import httpx
from fastapi.testclient import TestClient
from server.api.main import create_app
from server.application.a_gateway import AServiceClient
from server.configuration.settings import Settings

@pytest.fixture
def client():
    settings=Settings(username='admin',password='UnitTest-Password-2026!',secret='test-secret-'*8,
                      origins=('http://127.0.0.1:5173',))
    with TestClient(create_app(settings)) as c: yield c

def signin(client):
    response=client.post('/api/admin/sessions',json={'username':'admin','password':'UnitTest-Password-2026!'})
    assert response.status_code==200
    return response.json()

def test_anonymous_is_rejected(client):
    assert client.get('/api/admin/session').status_code==401
    assert client.get('/api/admin/probe').status_code==401
    assert client.post('/api/admin/probe').status_code==401

def test_password_checked_on_server(client):
    response=client.post('/api/admin/sessions',json={'username':'admin','password':'wrong-password'})
    assert response.status_code==401
    assert 'wrong-password' not in response.text
    assert client.get('/api/admin/probe').status_code==401

def test_cookie_and_current_session(client):
    session=signin(client)
    assert session['role']=='admin' and session['csrf_token']
    assert client.get('/api/admin/session').json()['username']=='admin'
    assert client.get('/api/admin/probe').status_code==200
    assert client.cookies.get('cvkg_session')

def test_writes_need_csrf_and_do_not_import_data(client):
    session=signin(client)
    assert client.post('/api/admin/probe').status_code==403
    result=client.post('/api/admin/probe',headers={'X-CSRF-Token':session['csrf_token']})
    assert result.status_code==200 and result.json()['data_changed'] is False

def test_logout_revokes_replayed_cookie(client):
    session=signin(client)
    old=client.cookies.get('cvkg_session')
    assert client.delete('/api/admin/session',headers={'X-CSRF-Token':session['csrf_token']}).status_code==204
    assert client.get('/api/admin/probe').status_code==401
    replay=client.get('/api/admin/probe',headers={'Cookie':f'cvkg_session={old}'})
    assert replay.status_code==401

def test_login_rotates_and_revokes_prior_session(client):
    signin(client);old=client.cookies.get('cvkg_session')
    signin(client)
    assert client.get('/api/admin/probe',headers={'Cookie':f'cvkg_session={old}'}).status_code==401

def test_expiration_is_enforced_server_side(client):
    signin(client)
    for session in client.app.state.auth.sessions.values():session.expires=time.time()-1
    assert client.get('/api/admin/probe').status_code==401

def test_origin_rejected_before_login(client):
    response=client.post('/api/admin/sessions',json={'username':'admin','password':'UnitTest-Password-2026!'},headers={'Origin':'https://untrusted.example'})
    assert response.status_code==403

def test_login_rate_limit(client):
    for _ in range(5):
        assert client.post('/api/admin/sessions',json={'username':'admin','password':'incorrect'}).status_code==401
    assert client.post('/api/admin/sessions',json={'username':'admin','password':'UnitTest-Password-2026!'}).status_code==429

def test_unicode_username_is_401_not_server_error(client):
    assert client.post('/api/admin/sessions',json={'username':'演示用户','password':'UnitTest-Password-2026!'}).status_code==401

def test_validation_never_echoes_password(client):
    password='x'*300
    response=client.post('/api/admin/sessions',json={'username':'admin','password':password})
    assert response.status_code==422 and password not in response.text

def test_cookie_flags_and_no_store(client):
    response=client.post('/api/admin/sessions',json={'username':'admin','password':'UnitTest-Password-2026!'})
    cookie=response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie
    assert response.headers['cache-control']=='no-store'
    assert response.headers['x-request-id']

def test_a_admin_proxy_requires_d_session_and_csrf(client, monkeypatch):
    calls=[]
    async def fake_request(_self, method, path, **kwargs):
        calls.append((method,path,kwargs))
        return httpx.Response(200,json={'ok':True})
    monkeypatch.setattr(AServiceClient,'request',fake_request)
    assert client.get('/api/admin/datasets').status_code==401
    session=signin(client)
    assert client.get('/api/admin/datasets').status_code==200
    assert client.post('/api/admin/imports',json={'dataset_id':'sample'}).status_code==403
    response=client.post('/api/admin/imports',json={'dataset_id':'sample'},headers={'X-CSRF-Token':session['csrf_token']})
    assert response.status_code==200
    assert calls[0][0:2]==('GET','/api/admin/datasets')
    assert calls[1][0:2]==('POST','/api/admin/imports')
