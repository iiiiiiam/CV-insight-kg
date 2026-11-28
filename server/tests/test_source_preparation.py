"""Offline local-ledger automation: missing sources never gate public results."""
from dataclasses import asdict, replace
import threading
import time
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

from server.api.main import create_app
from server.application.source_preparation import SourcePreparation
from server.configuration.settings import Settings
from src.knowledge_builder.batches import BatchRegistry
from src.knowledge_builder.enrichment_sources import SourceUnavailable
from src.knowledge_builder.extraction import fingerprint
from src.knowledge_builder.models import PaperInput


def sample():
    paper=PaperInput('https://openalex.org/W1','Vision paper','We evaluate COCO for image segmentation.',2024,'CVPR',[{'author':{'display_name':'Ada'}}],
                     'https://openalex.org/W1','source-check')
    payload=dict(id=paper.openalex_id,display_name=paper.title,publication_year=2024,topics=[],keywords=[])
    annotation=dict(source='openalex',url='https://api.openalex.org/works/W1',
                    fetched_at='2026-11-28T00:00:00Z',payload=payload,digest=fingerprint(payload))
    document=dict(format_version='a-paperinput/1',batch_id=1,batch_code='AUTO-1',total_papers=1,
                  exported_papers=1,excluded_papers=0,excluded=[],items=[asdict(paper)],
                  source_annotations=[dict(paper_id=paper.openalex_id,record=annotation)])
    return paper,document


def settings(root, automatic=False):
    return Settings(username='source-test',password='source-test-password',secret='s'*48,
                    auto_graph_sync=False,auto_source_enrichment=automatic,
                    user_store=str(root/'users.json'),b_batch_registry=str(root/'ledger.json'),
                    b_source_offline=True,b_source_cache=str(root/'cache'))


def wait_for(predicate, timeout=3):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Background source task did not reach the expected state')


def test_local_batch_sources_run_automatically_without_blocking_effective(tmp_path,monkeypatch):
    monkeypatch.setattr(SourcePreparation,'poll_seconds',.02)
    paper,document=sample()
    started,release=threading.Event(),threading.Event()
    def slow_source(_paper):
        started.set()
        assert release.wait(3)
        payload=dict(title=paper.title,authors=['Ada'],published='2024-01-01',tasks=[{'name':'Image segmentation'}],methods=[],datasets=[])
        return dict(source='paperswithcode',url='https://example.test/catalog',fetched_at='2026-11-28T00:00:00Z',
                    payload=payload,digest=fingerprint(payload))
    source=Mock(openalex=Mock(side_effect=AssertionError('OpenAlex already supplied')),papers_with_code=slow_source)
    class FakeC:
        def __init__(self):
            self.rows={};self.active=None;self.published=[]
        async def batch(self, identifier):
            return httpx.Response(200,json=self.rows[identifier]) if identifier in self.rows else httpx.Response(404)
        async def request(self, method, path, *, body=None, **kwargs):
            if path=='/api/admin/graph/publication-status':
                return httpx.Response(200,json=dict(items=[],active_batch_id=self.active,publish_generation=len(self.published)))
            if path=='/api/admin/graph/effective':
                identifier='effective-'+body['revision']
                self.rows[identifier]=dict(id=identifier,provenance='effective_export',publishable=True,
                                           source_revision=body['revision'],status='ready')
                return httpx.Response(200,json=dict(id=identifier,replay=False))
            if path.endswith('/publish'):
                self.active=path.split('/')[-2]
                self.published.append(self.active)
                return httpx.Response(200,json=dict(batch_id=self.active,status='published',publish_generation=len(self.published)))
            raise AssertionError(path)
    graph=FakeC()
    BatchRegistry(tmp_path/'ledger.json').ingest(document)
    app=create_app(replace(settings(tmp_path,True),auto_graph_sync=True,graph_sync_interval_seconds=.02))
    with patch('src.knowledge_builder.batch_sources.SourceClient',return_value=source), patch('server.api.main.CServiceClient',return_value=graph):
        with TestClient(app) as client:
            try:
                # Same direct B module path as A local transport; no HTTP ingest or manual retry.
                assert started.wait(3)
                wait_for(lambda:bool(graph.published))
                login=client.post('/api/admin/sessions',json=dict(username='source-test',password='source-test-password'))
                assert login.status_code==200
                before=client.get('/api/admin/knowledge/effective-export')
                assert before.status_code==200 and before.json()['counts']['papers']==1
                state=client.get('/api/admin/knowledge/batches/readiness').json()
                assert state['source_enrichment']['running'] is True
                assert state['results']['available'] is True
                assert 'effective-'+before.json()['revision'] in graph.published
                release.set()
                wait_for(lambda:not app.state.source_preparation.status()['running'])
                after=client.get('/api/admin/knowledge/effective-export')
                assert after.status_code==200
                assert after.json()['revision']!=before.json()['revision']
                wait_for(lambda:graph.active=='effective-'+after.json()['revision'])
                assert client.get('/api/admin/knowledge/batches/readiness').json()['source_enrichment']['state']=='complete'
                source.openalex.assert_not_called()
            finally:
                release.set()


def test_partial_sources_retry_without_manual_action_and_share_http_slot(tmp_path):
    _,document=sample()
    BatchRegistry(tmp_path/'ledger.json').ingest(document)
    job=SourcePreparation(settings(tmp_path))
    source=Mock(openalex=Mock(side_effect=AssertionError('Already supplied')),
                papers_with_code=Mock(side_effect=SourceUnavailable('offline')))
    with patch('src.knowledge_builder.batch_sources.SourceClient',return_value=source):
        job.check()
        assert source.papers_with_code.call_count==1
        job.check()
        assert source.papers_with_code.call_count==1  # No network retry at every poll.
        job.next_attempt=0
        job.check()
        assert source.papers_with_code.call_count==2
        queued=[]
        job.schedule(queued.append)
        job.check()
        job.schedule(queued.append)
        assert len(queued)==1  # HTTP/manual trigger cannot duplicate a running slot.
        queued[0]()
        assert not job.status()['running']
        assert source.papers_with_code.call_count==3


def test_watcher_does_not_fetch_demo_corpus_without_managed_batches(tmp_path):
    with patch('src.knowledge_builder.batch_sources.SourceClient',side_effect=AssertionError('No managed batch')):
        job=SourcePreparation(settings(tmp_path))
        job.check()
        assert not job.status()['running']
