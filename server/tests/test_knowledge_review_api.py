"""HTTP auth, write scope and download/public-view contracts; temp archives only."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.knowledge import KnowledgeSnapshot
from server.configuration.settings import Settings
from src.knowledge_builder.models import Entity, Relation


@pytest.fixture
def context(tmp_path):
    settings = Settings(username='D-admin-program-test', password='UnitTest-Password-2026!',
                        secret='review-api-test-' * 5, b_reviews_directory=str(tmp_path))
    snapshot = KnowledgeSnapshot(reviews_directory=tmp_path)
    identifier = snapshot.papers[0].openalex_id
    items = snapshot.sessions[identifier].items
    ids = {kind: next(item.candidate_id for item in items if isinstance(item.content, Entity) and item.content.kind == kind)
           for kind in ('paper', 'task')}
    ids['relation'] = next(item.candidate_id for item in items if isinstance(item.content, Relation) and item.content.kind == 'mentions_task')
    with TestClient(create_app(settings)) as client:
        yield client, settings, identifier, ids, tmp_path


def login(client, settings):
    response = client.post('/api/admin/sessions', json={'username': settings.username, 'password': settings.password})
    assert response.status_code == 200
    return {'X-CSRF-Token': response.json()['csrf_token']}


def body(client, identifier, candidate, action='confirm', **kwargs):
    revision = client.get('/api/admin/knowledge/snapshot').json()['snapshot_revision']
    return {'paper_id': identifier, 'candidate_id': candidate, 'action': action,
            'reason': 'HTTP program test only, not human annotation', 'snapshot_revision': revision, **kwargs}


def test_admin_and_csrf_required_for_real_review(context):
    client, settings, identifier, ids, path = context
    revision = KnowledgeSnapshot(reviews_directory=path).snapshot_revision
    payload = {'paper_id': identifier, 'candidate_id': ids['paper'], 'action': 'confirm',
               'reason': 'Program test', 'snapshot_revision': revision}
    assert client.post('/api/admin/knowledge/reviews', json=payload).status_code == 401
    assert client.get('/api/admin/knowledge/exports/bundle.zip', params={'snapshot_revision': revision}).status_code == 401
    assert client.get('/api/knowledge/confirmed', params={'paper_id': identifier}).json()['entities'] == []
    login(client, settings)
    assert client.post('/api/admin/knowledge/reviews', json=payload).status_code == 403
    assert list(path.iterdir()) == []


def test_actor_cannot_be_spoofed_and_evidence_cannot_be_written(context):
    client, settings, identifier, ids, path = context
    headers = login(client, settings)
    for extra in ({'reviewer': 'forged'}, {'evidence': []}, {'action': 'edit_evidence'}):
        payload = body(client, identifier, ids['paper'])
        payload.update(extra)
        assert client.post('/api/admin/knowledge/reviews', json=payload, headers=headers).status_code == 422
    assert list(path.iterdir()) == []
    response = client.post('/api/admin/knowledge/reviews', json=body(client, identifier, ids['paper']), headers=headers)
    assert response.status_code == 200 and response.json()['saved']
    detail = client.get('/api/admin/knowledge/candidates', params={'paper_id': identifier}).json()
    assert detail['review']['history'][-1]['reviewer'] == settings.username
    assert all(c['status'] == 'pending' for c in detail['result']['entities'])


def test_full_workflow_downloads_and_public_projection(context):
    client, settings, identifier, ids, _path = context
    headers = login(client, settings)
    rejected = client.post('/api/admin/knowledge/reviews', json=body(client, identifier, ids['relation']), headers=headers)
    assert rejected.status_code == 422
    rename = body(client, identifier, ids['task'], 'correct', name='程序测试的显示名')
    assert client.post('/api/admin/knowledge/reviews', json=rename, headers=headers).status_code == 200
    assert client.post('/api/admin/knowledge/reviews', json=rename, headers=headers).status_code == 409
    for key in ('paper', 'task', 'relation'):
        assert client.post('/api/admin/knowledge/reviews', json=body(client, identifier, ids[key]), headers=headers).status_code == 200
    public = client.get('/api/knowledge/confirmed', params={'paper_id': identifier})
    assert public.status_code == 200
    assert len(public.json()['entities']) == 2 and len(public.json()['relations']) == 1
    assert '程序测试的显示名' in public.text
    assert 'HTTP program test' not in public.text and settings.username not in public.text
    revision = client.get('/api/admin/knowledge/snapshot').json()['snapshot_revision']
    download = client.get('/api/admin/knowledge/exports/confirmed.json', params={'snapshot_revision': revision})
    assert download.status_code == 200 and download.json()['counts']['relations'] == 1
    assert 'attachment' in download.headers['content-disposition']
    bundle = client.get('/api/admin/knowledge/exports/bundle.zip', params={'snapshot_revision': revision})
    assert bundle.headers['content-type'] == 'application/zip'
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        assert len(archive.namelist()) == 5
        assert json.loads(archive.read('manifest.json'))['counts']['confirmed']['relations'] == 1
    assert client.post('/api/admin/knowledge/reviews', json=body(client, identifier, ids['task'], 'reopen'), headers=headers).status_code == 200
    assert client.get('/api/knowledge/confirmed', params={'paper_id': identifier}).json()['relations'] == []
    assert client.get('/api/admin/knowledge/exports/bundle.zip', params={'snapshot_revision': revision}).status_code == 409


def test_public_bad_archive_error_does_not_disclose_private_paths(context):
    client, _settings, identifier, _ids, path = context
    (path / 'broken.json').write_text('{}', encoding='utf-8')
    response = client.get('/api/knowledge/confirmed', params={'paper_id': identifier})
    assert response.status_code == 409
    assert str(path) not in response.text
    assert 'items' not in response.json() and 'entities' not in response.json()
