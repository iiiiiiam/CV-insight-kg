from pathlib import Path
from dataclasses import asdict
import hashlib
from collections import Counter
import tempfile

from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.knowledge import KnowledgeSnapshot
from server.configuration.settings import Settings
from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.input_adapter import load_openalex_sample
from src.knowledge_builder.review_storage import save_review


def test_adapter_uses_actual_b_results_and_preserves_inputs():
    root = Path(__file__).resolve().parents[2]
    files = [root / 'examples/week1_baseline.json', root / 'examples/cvpr_2024_seed.jsonl']
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    directory = tempfile.TemporaryDirectory()
    snapshot = KnowledgeSnapshot(reviews_directory=directory.name)
    summary = snapshot.overview()
    assert len(summary['papers']) == 20
    assert summary['status'] == 'review_snapshot' and summary['confirmed_count'] == 0
    assert summary['entity_counts'] == dict(Counter(c.entity.kind for r in snapshot.results.values() for c in r.entities))
    paper = load_openalex_sample(files[0])[0]
    response = snapshot.candidates(paper.openalex_id)
    assert response['result'] == asdict(extract_candidates(paper))
    assert all(c['status'] == 'pending' for c in response['result']['relations'])
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    directory.cleanup()


def test_knowledge_is_protected_read_only_and_rejects_unknown_papers(tmp_path):
    settings = Settings(username='admin', password='UnitTest-Password-2026!', secret='k-test-' * 10,
                        b_reviews_directory=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/admin/knowledge/snapshot').status_code == 401
        assert client.post('/api/admin/sessions', json={'username': settings.username, 'password': settings.password}).status_code == 200
        overview = client.get('/api/admin/knowledge/snapshot').json()
        paper_id = overview['papers'][0]['openalex_id']
        result = client.get('/api/admin/knowledge/candidates', params={'paper_id': paper_id})
        assert result.status_code == 200 and result.json()['read_only']
        assert client.get('/api/admin/knowledge/candidates', params={'paper_id': 'missing'}).status_code == 404
        assert client.post('/api/admin/knowledge/candidates', json={'status': 'confirmed'}).status_code == 405


def test_http_reads_reload_archives_and_reject_stale_revision(tmp_path):
    settings = Settings(username='admin', password='UnitTest-Password-2026!', secret='refresh-test-' * 8,
                        b_reviews_directory=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        client.post('/api/admin/sessions', json={'username': settings.username, 'password': settings.password})
        before = client.get('/api/admin/knowledge/snapshot').json()
        snapshot = KnowledgeSnapshot(reviews_directory=tmp_path)
        identifier = snapshot.papers[0].openalex_id
        session = snapshot.sessions[identifier]
        session.confirm(session.items[0].candidate_id, reviewer='D-program-test', reason='Program test, not human annotation')
        save_review(tmp_path / 'program-test.json', session)
        after = client.get('/api/admin/knowledge/snapshot').json()
        assert after['confirmed_count'] == 1 and after['snapshot_revision'] != before['snapshot_revision']
        stale = client.get('/api/admin/knowledge/candidates', params={'paper_id': identifier, 'snapshot_revision': before['snapshot_revision']})
        assert stale.status_code == 409
        assert stale.json()['error']['code'] == 'KNOWLEDGE_SNAPSHOT_CHANGED'
        current = client.get('/api/admin/knowledge/candidates', params={'paper_id': identifier, 'snapshot_revision': after['snapshot_revision']})
        assert current.status_code == 200 and current.json()['review']['has_archive']
        assert current.headers['cache-control'] == 'no-store'


def test_invalid_archives_do_not_disable_auth_or_silently_reset_reviews(tmp_path):
    path = tmp_path / 'broken.json'
    body = b'{invalid-json'
    path.write_bytes(body)
    settings = Settings(username='admin', password='UnitTest-Password-2026!', secret='invalid-test-' * 8,
                        b_reviews_directory=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/admin/knowledge/snapshot').status_code == 401
        assert client.post('/api/admin/sessions', json={'username': settings.username, 'password': settings.password}).status_code == 200
        result = client.get('/api/admin/knowledge/snapshot')
        assert result.status_code == 409
        assert result.json()['error']['code'] == 'KNOWLEDGE_SNAPSHOT_INVALID'
        assert 'review_counts' not in result.json()
        assert client.get('/api/admin/probe').status_code == 200
        assert path.read_bytes() == body
