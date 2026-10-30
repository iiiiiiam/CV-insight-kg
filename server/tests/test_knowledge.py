from pathlib import Path
from dataclasses import asdict
import hashlib

from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.knowledge import KnowledgeSnapshot
from server.configuration.settings import Settings
from src.knowledge_builder.extraction import extract_candidates
from src.knowledge_builder.input_adapter import load_openalex_sample


def test_adapter_uses_actual_b_results_and_preserves_inputs():
    root = Path(__file__).resolve().parents[2]
    files = [root / 'examples/week1_baseline.json', root / 'examples/cvpr_2024_seed.jsonl']
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
    snapshot = KnowledgeSnapshot()
    summary = snapshot.overview()
    assert len(summary['papers']) == 20
    assert summary['status'] == 'pending' and summary['confirmed_count'] == 0
    assert summary['entity_counts'].get('topic', 0) == 0  # No invented topic labels.
    paper = load_openalex_sample(files[0])[0]
    response = snapshot.candidates(paper.openalex_id)
    assert response['result'] == asdict(extract_candidates(paper))
    assert all(c['status'] == 'pending' for c in response['result']['relations'])
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]


def test_knowledge_is_protected_read_only_and_rejects_unknown_papers():
    settings = Settings(username='admin', password='UnitTest-Password-2026!', secret='k-test-' * 10)
    with TestClient(create_app(settings)) as client:
        assert client.get('/api/admin/knowledge/snapshot').status_code == 401
        assert client.post('/api/admin/sessions', json={'username': settings.username, 'password': settings.password}).status_code == 200
        overview = client.get('/api/admin/knowledge/snapshot').json()
        paper_id = overview['papers'][0]['openalex_id']
        result = client.get('/api/admin/knowledge/candidates', params={'paper_id': paper_id})
        assert result.status_code == 200 and result.json()['read_only']
        assert client.get('/api/admin/knowledge/candidates', params={'paper_id': 'missing'}).status_code == 404
        assert client.post('/api/admin/knowledge/candidates', json={'status': 'confirmed'}).status_code == 405
