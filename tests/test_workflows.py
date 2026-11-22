"""Real database/worker/package tests; external HTTP is isolated at the boundary."""
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from sqlalchemy import select

from app.models import Job, WorkflowTask
from app.formal_batches import queue_batch, process_batch, withdraw_batch
from app.workflow_tasks import run_one, recover
from tests.test_formal_batches import record
from tests import test_formal_api


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        test_formal_api.FormalApiTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.artifacts = patch.dict(os.environ, {'A_REPORT_ROOT': self.temp.name})
        self.artifacts.start()

    def tearDown(self):
        self.artifacts.stop()
        self.temp.cleanup()
        test_formal_api.FormalApiTests.tearDown(self)

    def ingest(self, key, rows):
        with self.factory() as db:
            job, _ = queue_batch(db, key, 'CVPR', 2024, rows)
            process_batch(db, job)
            return job.id

    def create(self, **kwargs):
        response = self.client.post('/api/admin/reports', headers=self.auth, json=kwargs)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def detail(self, identifier, kind='reports'):
        response = self.client.get(f'/api/admin/{kind}/{identifier}', headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def bundle(self, identifier):
        response = self.client.get(f'/api/admin/reports/{identifier}/download', headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), response.headers['x-content-sha256'])
        return zipfile.ZipFile(io.BytesIO(response.content))

    def test_report_freezes_data_and_manifest_checks_every_file(self):
        self.ingest('first', [record(1), record(2, doi=None)])
        report = self.create(request_key='freeze', title='本周论文报告')
        self.assertEqual(self.client.get(f'/api/admin/reports/{report["id"]}/download', headers=self.auth).status_code, 409)
        self.ingest('after-create', [record(3)])
        self.assertTrue(run_one(self.factory))
        result = self.detail(report['id'])
        self.assertEqual((result['status'], result['progress'], result['attempts']), ('succeeded', 100, 1))
        self.assertEqual(result['result']['paper_count'], 2)
        with self.bundle(report['id']) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(manifest['paper_count'], 2)
            self.assertEqual(manifest['missing_providers'], ['B', 'C'])
            for item in manifest['files']:
                body = bundle.read(item['name'])
                self.assertEqual(len(body), item['bytes'])
                self.assertEqual(hashlib.sha256(body).hexdigest(), item['sha256'])
            for line in bundle.read('checksums.sha256').decode().splitlines():
                checksum, name = line.split('  ')
                self.assertEqual(hashlib.sha256(bundle.read(name)).hexdigest(), checksum)
            quality = json.loads(bundle.read('quality.json'))
            self.assertEqual(quality['missing']['doi'], ['https://openalex.org/W2'])
            summary = json.loads(bundle.read('summary.json'))
            self.assertEqual(summary['paper_count'], 2)
            self.assertEqual(summary['conference_years'], [{'venue': 'CVPR', 'year': 2024, 'paper_count': 2}])
            self.assertEqual(summary['sources'], [{'source': 'openalex', 'paper_count': 2}])
            self.assertEqual(summary['field_quality']['doi']['completeness_ratio'], .5)
            self.assertIsNone(summary['batch_changes'])
            self.assertIn('## 数据概述', bundle.read('report.md').decode())
            self.assertIn('<h2>数据概述</h2>', bundle.read('report.html').decode())
            self.assertEqual(self.client.get(f'/api/admin/reports/{report["id"]}/files/summary.json', headers=self.auth).json(), summary)
            self.assertIn('来源', bundle.read('report.md').decode())
        self.assertEqual(self.client.get('/api/admin/reports?status=succeeded', headers=self.auth).json()['total'], 1)

    def test_idempotency_conflict_and_unchanged_retry_rules(self):
        first = self.create(request_key='repeat')
        self.assertEqual(self.create(request_key='repeat')['id'], first['id'])
        self.assertTrue(self.create(request_key='repeat')['replay'])
        self.assertEqual(self.client.post('/api/admin/reports', headers=self.auth,
            json={'request_key': 'repeat', 'title': 'changed'}).status_code, 409)
        self.assertEqual(self.client.post(f'/api/admin/reports/{first["id"]}/retry', headers=self.auth).status_code, 409)
        run_one(self.factory)
        self.assertEqual(self.client.post(f'/api/admin/reports/{first["id"]}/retry', headers=self.auth).status_code, 409)

    def test_failure_retry_keeps_frozen_input_and_restart_recovers_running_task(self):
        self.ingest('first', [record(1)])
        task = self.create()
        with patch('app.report_bundle.generate', side_effect=OSError('Disk unavailable')):
            run_one(self.factory)
        self.assertEqual(self.detail(task['id'])['status'], 'failed')
        self.ingest('later', [record(2)])
        self.assertEqual(self.client.post(f'/api/admin/reports/{task["id"]}/retry', headers=self.auth).status_code, 202)
        with self.factory() as db:
            row = db.get(WorkflowTask, task['id'])
            row.status = 'running'
            db.commit()
        recover(self.factory)
        run_one(self.factory)
        result = self.detail(task['id'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['result']['paper_count'], 1)
        self.assertEqual(result['attempts'], 2)

    def test_selected_batch_keeps_original_metadata_after_withdrawal(self):
        first = self.ingest('first', [record(1), record(2)])
        second = self.ingest('second', [record(2, cited_by_count=9), record(3)])
        task = self.create(scope={'batch_ids': [second]})
        with self.factory() as db:
            withdraw_batch(db, second, 'test restore')
        run_one(self.factory)
        with self.bundle(task['id']) as bundle:
            papers = json.loads(bundle.read('papers.json'))
            self.assertEqual([p['cited_by_count'] for p in papers], [9, 1])
            self.assertEqual(json.loads(bundle.read('manifest.json'))['scope_mode'], 'selected_batches_historical')
        current = self.create()
        run_one(self.factory)
        self.assertEqual(self.detail(current['id'])['result']['paper_count'], 2)

    def test_summary_freezes_batch_changes_and_uses_unique_papers_for_sources(self):
        first = self.ingest('first', [record(1), record(2)])
        second = self.ingest('second', [record(2, cited_by_count=9), record(3)])
        task = self.create(scope={'batch_ids': [first, second]})
        with self.factory() as db:
            withdraw_batch(db, second, 'withdraw after summary snapshot')
        run_one(self.factory)
        with self.bundle(task['id']) as bundle:
            summary = json.loads(bundle.read('summary.json'))
            self.assertEqual(summary['paper_count'], 3)
            self.assertEqual(summary['sources'][0]['paper_count'], 3)
            self.assertEqual(summary['batch_changes'], {'added': 3, 'duplicate': 0, 'updated': 1, 'withdrawn': 0, 'failed': 0})
            self.assertEqual(summary['selected_batch_count'], 2)
        withdrawn = self.create(scope={'batch_ids': [second]})
        run_one(self.factory)
        with self.bundle(withdrawn['id']) as bundle:
            self.assertEqual(json.loads(bundle.read('summary.json'))['batch_changes']['withdrawn'], 2)

    def test_empty_summary_marks_completeness_as_unavailable(self):
        task = self.create()
        run_one(self.factory)
        with self.bundle(task['id']) as bundle:
            summary = json.loads(bundle.read('summary.json'))
            self.assertEqual(summary['paper_count'], 0)
            self.assertEqual(summary['sources'], [])
            self.assertIsNone(summary['field_quality']['abstract']['completeness_ratio'])

    def test_sections_reject_other_paper_sets_and_accept_matching_versions(self):
        self.ingest('first', [record(1)])
        section = {'provider': 'C', 'revision': 'statistics-v1', 'paper_ids': ['wrong'], 'data': {'years': []}}
        self.assertEqual(self.client.post('/api/admin/reports', headers=self.auth, json={'sections': [section]}).status_code, 409)
        section['paper_ids'] = ['https://openalex.org/W1']
        task = self.create(sections=[section])
        run_one(self.factory)
        with self.bundle(task['id']) as bundle:
            self.assertEqual(json.loads(bundle.read('c-data.json')), section)
            self.assertEqual(json.loads(bundle.read('manifest.json'))['missing_providers'], ['B'])

    def test_paper_selection_and_statistics_version_are_checked(self):
        self.ingest('first', [record(1), record(2)])
        task = self.create(scope={'paper_ids': ['https://openalex.org/W2']})
        run_one(self.factory)
        self.assertEqual(self.detail(task['id'])['result']['paper_count'], 1)
        invalid = self.client.post('/api/admin/reports', headers=self.auth,
            json={'scope': {'paper_ids': ['missing-paper']}})
        self.assertEqual(invalid.status_code, 409)
        section = {'provider': 'C', 'revision': 'rev', 'paper_ids': ['https://openalex.org/W1', 'https://openalex.org/W2'],
            'data': {'batch_id': 'effective-rev', 'statistics': {'paper_count': 999, 'batch_id': 'effective-rev'}}}
        self.assertEqual(self.client.post('/api/admin/reports', headers=self.auth,
            json={'sections': [section]}).status_code, 409)

    def test_download_rejects_missing_tampered_and_unlisted_files(self):
        task = self.create()
        run_one(self.factory)
        root = Path(self.temp.name) / self.detail(task['id'])['result']['artifact_directory']
        self.assertEqual(self.client.get(f'/api/admin/reports/{task["id"]}/files/payload.json', headers=self.auth).status_code, 404)
        self.assertEqual(self.client.get(f'/api/admin/reports/{task["id"]}/files/manifest.json', headers=self.auth).status_code, 200)
        (root/'report.zip').write_bytes(b'bad archive')
        self.assertEqual(self.client.get(f'/api/admin/reports/{task["id"]}/download', headers=self.auth).status_code, 409)

    def test_report_html_is_readable_and_escapes_title_and_csv_formula(self):
        self.ingest('first', [record(1, display_name='=Spreadsheet formula')])
        task = self.create(title='<script>alert(1)</script>论文报告')
        run_one(self.factory)
        with self.bundle(task['id']) as bundle:
            page = bundle.read('report.html').decode()
            self.assertIn('<h1>', page)
            self.assertIn('<h2>数据质量</h2>', page)
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)
            self.assertIn("'=Spreadsheet formula", bundle.read('papers.csv').decode())

    def test_busy_snapshot_can_be_resubmitted_without_partial_task(self):
        from sqlalchemy.exc import OperationalError
        with patch('app.report_bundle.snapshot', side_effect=OperationalError('insert', {}, Exception('busy'))):
            response = self.client.post('/api/admin/reports', headers=self.auth, json={'request_key': 'busy'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get('/api/admin/reports', headers=self.auth).json()['total'], 0)
        self.assertEqual(self.create(request_key='busy')['status'], 'queued')

    def test_all_new_endpoints_require_auth_and_invalid_ids_stay_isolated(self):
        for route in ('reports', 'handoffs'):
            self.assertEqual(self.client.get(f'/api/admin/{route}').status_code, 401)
            self.assertEqual(self.client.post(f'/api/admin/{route}', json={}).status_code, 401)
            self.assertEqual(self.client.get(f'/api/admin/{route}/unknown', headers=self.auth).status_code, 404)
        self.assertEqual(self.client.get('/api/admin/reports?status=bad', headers=self.auth).status_code, 422)

    def test_handoff_stale_revision_fails_and_can_retry_after_configuration(self):
        batch = self.ingest('first', [record(1)])
        revision = self.client.get(f'/api/admin/formal/batches/{batch}', headers=self.auth).json()['batch_revision']
        body = dict(batch_id=batch, expected_revision=revision, acknowledge_switch=True, request_key='send')
        response = self.client.post('/api/admin/handoffs', headers=self.auth, json=body)
        self.assertEqual(response.status_code, 202, response.text)
        identifier = response.json()['id']
        with patch.dict(os.environ, {'B_API_BASE_URL': ''}):
            run_one(self.factory)
        self.assertEqual(self.detail(identifier, 'handoffs')['status'], 'failed')
        self.assertEqual(self.client.post(f'/api/admin/handoffs/{identifier}/retry', headers=self.auth).status_code, 202)
        with self.factory() as db:
            withdraw_batch(db, batch, 'changed before sending')
        run_one(self.factory)
        self.assertIn('批次已更新或撤回', self.detail(identifier, 'handoffs')['error'])
        self.assertEqual(self.client.post('/api/admin/handoffs', headers=self.auth,
            json={**body, 'request_key': 'new'}).status_code, 409)

    def test_queue_handles_two_tasks_then_is_empty_and_schema_persists(self):
        a, b = self.create(request_key='a'), self.create(request_key='b')
        self.assertTrue(run_one(self.factory))
        self.assertTrue(run_one(self.factory))
        self.assertFalse(run_one(self.factory))
        self.assertEqual(self.detail(a['id'])['status'], 'succeeded')
        self.assertEqual(self.detail(b['id'])['status'], 'succeeded')

    def test_polling_does_not_load_frozen_paper_payload(self):
        from sqlalchemy import event
        task = self.create(title='Light progress')
        statements = []
        def capture(conn, cursor, statement, *args):
            statements.append(statement)
        event.listen(self.engine, 'before_cursor_execute', capture)
        try:
            self.assertEqual(self.detail(task['id'])['title'], 'Light progress')
            self.client.get('/api/admin/reports', headers=self.auth)
        finally:
            event.remove(self.engine, 'before_cursor_execute', capture)
        self.assertFalse(any('payload_json' in sql for sql in statements), statements)


    def knowledge_section(self, identifiers):
        from app.formal_batches import batch_manifest
        from src.knowledge_builder.batches import BatchRegistry
        from src.knowledge_builder.report_knowledge import build_report_knowledge
        registry = BatchRegistry(Path(self.temp.name)/'b-ledger.json')
        with self.factory() as db:
            for identifier in identifiers:
                registry.ingest(batch_manifest(db, identifier))
        knowledge = registry.workspace(Path(self.temp.name)/'feedback.json').export_effective()
        report = build_report_knowledge(knowledge)
        return dict(provider='B', revision=knowledge['revision'],
                    paper_ids=report['scope']['paper_ids'], data=report)

    def test_b_week4_report_includes_real_tags_quality_and_checksums(self):
        identifier = self.ingest('b-report', [record(1, abstract_inverted_index={
            'We': [0], 'evaluate': [1], 'COCO': [2]})])
        section = self.knowledge_section([identifier])
        task = self.create(sections=[section])
        run_one(self.factory)
        with self.bundle(task['id']) as bundle:
            self.assertEqual(json.loads(bundle.read('b-report.json')), section['data'])
            tags = json.loads(bundle.read('b-author-tags.json'))
            self.assertEqual(tags, section['data']['author_tags'])
            self.assertEqual(bundle.read('b-labels.json'), bundle.read('b-author-tags.json'))
            self.assertTrue(tags['authors'][0]['tags'])
            quality = json.loads(bundle.read('b-quality.json'))
            self.assertEqual(quality['accuracy']['precision'], None)
            self.assertEqual(quality['knowledge_revision'], section['revision'])
            self.assertIn('不表示作者专长', bundle.read('report.md').decode())
            for item in json.loads(bundle.read('manifest.json'))['files']:
                self.assertEqual(hashlib.sha256(bundle.read(item['name'])).hexdigest(), item['sha256'])
        from copy import deepcopy
        invalid = deepcopy(section)
        invalid['data']['quality']['counts']['papers'] = 999
        response = self.client.post('/api/admin/reports', headers=self.auth, json={'sections': [invalid]})
        self.assertEqual(response.status_code, 409, response.text)
        mismatched = dict(provider='C', revision='other', paper_ids=section['paper_ids'],
                          data={'statistics': {'paper_count': 1, 'batch_id': 'effective-other'},
                                'batch_id': 'effective-other'})
        self.assertEqual(self.client.post('/api/admin/reports', headers=self.auth,
            json={'sections': [section, mismatched]}).status_code, 409)
        invalid = deepcopy(section)
        invalid['revision'] = invalid['data']['revision']
        self.assertEqual(self.client.post('/api/admin/reports', headers=self.auth,
            json={'sections': [invalid]}).status_code, 409)

    def test_withdrawal_notification_is_durable_idempotent_and_retryable(self):
        batch = self.ingest('withdraw-notify', [record(1)])
        revision = self.client.get(f'/api/admin/formal/batches/{batch}', headers=self.auth).json()['batch_revision']
        sent = self.client.post('/api/admin/handoffs', headers=self.auth, json={
            'batch_id': batch, 'expected_revision': revision, 'acknowledge_switch': True}).json()
        with patch('app.delivery.send', return_value={'received': True}):
            run_one(self.factory)
        withdrawn = self.client.post(f'/api/admin/jobs/{batch}/withdraw', headers=self.auth,
                                     json={'reason': 'Notify B too'})
        self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
        task = withdrawn.json()['b_notification']
        self.assertEqual(task['status'], 'queued')
        self.assertNotEqual(task['batch_revision'], revision)
        self.assertNotEqual(task['id'], sent['id'])
        repeated = self.client.post(f'/api/admin/jobs/{batch}/withdraw', headers=self.auth,
                                    json={'reason': 'Again'}).json()
        self.assertEqual(repeated['b_notification']['id'], task['id'])
        with patch('app.delivery.send', side_effect=ValueError('B unavailable')):
            run_one(self.factory)
        state = self.client.get(f'/api/admin/jobs/{batch}/withdrawal', headers=self.auth).json()
        self.assertEqual(state['b_notification']['status'], 'failed')
        self.assertEqual(self.client.get('/api/papers').json()['total'], 0)
        self.assertEqual(self.client.post(f'/api/admin/handoffs/{task["id"]}/retry', headers=self.auth).status_code, 202)
        with patch('app.delivery.send', return_value={'received': True}) as send:
            run_one(self.factory)
            self.assertEqual(send.call_args.args[1]['document']['state'], 'withdrawn')
        self.assertEqual(self.detail(task['id'], 'handoffs')['status'], 'succeeded')
        self.assertEqual(self.client.get(f'/api/admin/jobs/{batch}/withdrawal', headers=self.auth)
                         .json()['b_notification']['status'], 'succeeded')

    def test_unshared_withdrawal_does_not_queue_or_switch_b(self):
        batch = self.ingest('unshared', [record(1)])
        response = self.client.post(f'/api/admin/formal/batches/{batch}/withdraw', headers=self.auth,
                                    json={'reason': 'Local only'})
        self.assertEqual(response.json()['b_notification']['status'], 'not_required')
        self.assertEqual(self.client.get('/api/admin/handoffs', headers=self.auth).json()['total'], 0)

    def test_notification_failure_rolls_back_withdrawal(self):
        batch = self.ingest('atomic-withdraw', [record(1)])
        with self.factory() as db:
            with patch('app.delivery.queue_withdrawal_notification', side_effect=ValueError('queue failed')):
                with self.assertRaises(ValueError):
                    withdraw_batch(db, batch, 'must be atomic')
            db.rollback()
        self.assertEqual(self.client.get('/api/papers').json()['total'], 1)
        self.assertEqual(self.client.get(f'/api/admin/formal/batches/{batch}', headers=self.auth)
                         .json()['state'], 'active')


class WorkflowUpgradeTests(unittest.TestCase):
    def test_old_queue_is_upgraded_and_pending_report_can_complete(self):
        import sqlite3
        from app.models import database
        from app.workflow_tasks import view
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'old.db'
            payload = json.dumps({'title': 'Existing report', 'snapshot': {'papers': [], 'scope': {},
                'mode': 'current_effective', 'revision': 'old-revision', 'batches': []}, 'sections': []})
            with sqlite3.connect(path) as db:
                db.execute('''CREATE TABLE a_workflow_tasks (
                    id VARCHAR(32) PRIMARY KEY, kind VARCHAR(20), request_key VARCHAR(64) UNIQUE,
                    request_sha256 VARCHAR(64), status VARCHAR(20), stage VARCHAR(40), progress INTEGER,
                    attempts INTEGER, payload_json TEXT, result_json TEXT, error TEXT, events_json TEXT,
                    created_at DATETIME, updated_at DATETIME, finished_at DATETIME)''')
                db.execute('''INSERT INTO a_workflow_tasks VALUES
                    (?, 'report', ?, ?, 'queued', 'queued', 0, 0, ?, NULL, NULL, '[]',
                     '2026-11-17 00:00:00', '2026-11-17 00:00:00', NULL)''',
                     ('1'*32, 'a'*64, 'b'*64, payload))
            factory = database('sqlite:///'+str(path))
            try:
                with factory() as db:
                    self.assertEqual(view(db.get(WorkflowTask, '1'*32))['title'], 'Existing report')
                with patch.dict(os.environ, {'A_REPORT_ROOT': str(Path(directory)/'artifacts')}):
                    run_one(factory)
                with factory() as db:
                    self.assertEqual(db.get(WorkflowTask, '1'*32).status, 'succeeded')
            finally:
                factory.kw['bind'].dispose()


if __name__ == '__main__':
    unittest.main()
