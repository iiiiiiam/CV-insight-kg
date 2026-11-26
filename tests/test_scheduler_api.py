import json
import os
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import select, func

from app.models import CollectionSchedule, CollectionRun, CollectionTask, Job, Paper, now
from app.scheduler import ensure_default, tick, status
from app.formal_batches import process_batch, withdraw_batch
from app.delivery import batch_document
from tests import test_formal_api
from tests.test_formal_batches import record


class SchedulerApiTests(unittest.TestCase):
    def setUp(self):
        test_formal_api.FormalApiTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = patch.dict(os.environ, {'A_COLLECTION_ROOT': str(self.root/'baseline'),
                                            'A_SCHEDULE_ROOT': str(self.root/'captures')})
        self.paths.start()
        ensure_default(self.factory)
        baseline = self.root/'baseline/cvpr_2024'
        baseline.mkdir(parents=True)
        for name in ('baseline.html', 'baseline.json'):
            (baseline/name).write_text('isolated scheduler fixture')
        self.patches = [patch('app.scheduler.freeze_baseline'), patch('app.scheduler.load_baseline')]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.paths.stop()
        self.temp.cleanup()
        test_formal_api.FormalApiTests.tearDown(self)

    def data(self):
        result = self.client.get('/api/admin/formal/schedules', headers=self.auth)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def save(self, **change):
        plan = self.data()['schedules'][0]
        body = {k: plan[k] for k in ('enabled', 'time', 'timezone', 'scopes', 'with_annotations', 'max_attempts', 'retry_seconds')}
        body.update(expected_revision=plan['revision'], scopes=['CVPR:2024'])
        body.update(change)
        return self.client.put('/api/admin/formal/schedules/daily-papers', headers=self.auth, json=body)

    def collect(self, venue, year, directory, **kwargs):
        (directory/'formal-input.json').write_text(json.dumps({'format_version': 'a-formal-input/1',
            'venue': venue, 'year': year, 'records': [record(1), record(2)]}))

    def finish(self):
        with self.factory() as db:
            for job in db.scalars(select(Job).where(Job.status == 'queued')):
                process_batch(db, job)

    def test_default_disabled_auth_and_plan_changes_survive_restart(self):
        self.assertFalse(self.data()['schedules'][0]['enabled'])
        self.assertEqual(self.data()['schedules'][0]['scopes'], ['CVPR:2023', 'ICCV:2021'])
        self.assertFalse(self.data()['runtime']['connected'])
        self.assertNotIn('output_root', self.data()['schedules'][0])
        self.assertEqual(self.client.get('/api/admin/formal/schedules').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/formal/schedules/daily-papers/run').status_code, 401)
        self.assertEqual(self.save(enabled=True, time='10:15').status_code, 200)
        ensure_default(self.factory)
        plan = self.data()['schedules'][0]
        self.assertEqual((plan['enabled'], plan['time']), (True, '10:15'))
        self.assertTrue(plan['next_run_local'].endswith('10:15:00+08:00'))

    def test_revision_and_invalid_scope_or_timezone_do_not_overwrite_plan(self):
        old = self.data()['schedules'][0]
        self.assertEqual(self.save(time='10:00').status_code, 200)
        body = {k: old[k] for k in ('enabled', 'time', 'timezone', 'scopes')}
        body['expected_revision'] = old['revision']
        self.assertEqual(self.client.put('/api/admin/formal/schedules/daily-papers', headers=self.auth, json=body).status_code, 409)
        for invalid in ({'scopes': ['ICCV:2024']}, {'timezone': 'Missing/Timezone'}, {'scopes': ['CVPR:2024']*2}):
            self.assertEqual(self.save(**invalid).status_code, 422)
        self.assertEqual(self.data()['schedules'][0]['time'], '10:00')

    def test_manual_once_disabled_plan_reuses_active_run_and_creates_real_automatic_batch(self):
        self.assertEqual(self.save().status_code, 200)
        created = self.client.post('/api/admin/formal/schedules/daily-papers/run', headers=self.auth)
        again = self.client.post('/api/admin/formal/schedules/daily-papers/run', headers=self.auth)
        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json()['run_id'], again.json()['run_id'])
        self.assertTrue(again.json()['replay'])
        moment = now()
        tick(self.factory, moment, collector=self.collect)
        self.finish()
        tick(self.factory, moment+timedelta(seconds=1), collector=self.collect)
        run = self.data()['runs'][0]
        task = run['tasks'][0]
        self.assertEqual(run['status'], 'succeeded')
        self.assertTrue(task['display_code'].startswith('A-'))
        self.assertEqual(task['progress']['percent'], 100)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)), 2)
            self.assertEqual(batch_document(db, task['job_id'])['exported_papers'], 2)
            withdraw_batch(db, task['job_id'], 'scheduler API acceptance')
        self.assertEqual(self.data()['runs'][0]['tasks'][0]['batch_state'], 'withdrawn')
        report = self.client.post('/api/admin/reports', headers=self.auth, json={})
        self.assertEqual(report.status_code, 202)

    def test_failure_manual_retry_keeps_attempt_history_and_original_run(self):
        self.save(retry_seconds=1)
        identifier = self.client.post('/api/admin/formal/schedules/daily-papers/run', headers=self.auth).json()['run_id']
        moment = now()
        def broken(*args, **kwargs):
            raise OSError('Provider temporarily unavailable')
        for i in range(3):
            tick(self.factory, moment+timedelta(seconds=i), collector=broken)
        self.assertEqual(self.data()['runs'][0]['status'], 'failed')
        retried = self.client.post(f'/api/admin/formal/collection-runs/{identifier}/retry', headers=self.auth)
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(self.client.post(f'/api/admin/formal/collection-runs/{identifier}/retry', headers=self.auth).status_code, 409)
        tick(self.factory, moment+timedelta(seconds=4), collector=self.collect)
        self.finish()
        tick(self.factory, moment+timedelta(seconds=5), collector=self.collect)
        task = self.data()['runs'][0]['tasks'][0]
        self.assertEqual((task['status'], task['attempts'], task['retry_round']), ('succeeded', 4, 1))
        self.assertEqual(self.data()['runs'][0]['run_id'], identifier)

    def test_pause_stops_future_triggers_but_finishes_already_queued_run(self):
        self.save(enabled=True)
        with self.factory() as db:
            schedule = db.get(CollectionSchedule, 'daily-papers')
            schedule.next_run_at = now()-timedelta(minutes=1)
            db.commit()
        moment = now()
        tick(self.factory, moment, collector=self.collect)
        self.save(enabled=False)
        self.finish()
        tick(self.factory, moment+timedelta(seconds=1), collector=self.collect)
        self.assertEqual(self.data()['runs'][0]['status'], 'succeeded')
        tick(self.factory, moment+timedelta(days=3), collector=self.collect)
        self.assertEqual(len(self.data()['runs']), 1)
