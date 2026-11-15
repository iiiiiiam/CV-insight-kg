import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

from app.demo import create_demo
from app.demo_presentation import prepare_withdrawable
from app.data_overview import dashboard,handoff
from app.batch_withdrawal import withdraw_import
from app.batch_labels import batch_labels
from app.models import database,Job


class PresentationTests(unittest.TestCase):
    def test_prepare_balanced_batches_and_withdraw_one_without_losing_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'preview.db'
            create_demo(path)
            factory=database('sqlite:///'+str(path))
            try:
                result=prepare_withdrawable(factory,minimum=12)
                self.assertEqual(len(result['prepared_batches']),12)
                with factory() as db:
                    report=dashboard(db,14)
                    self.assertEqual(report['total_papers'],516)
                    self.assertTrue(all(30<=p['papers']<=38 for p in report['trend']))
                    for point in report['trend']:
                        self.assertEqual(sum(point['import_modes'].values()),point['papers'])
                    jobs=[db.get(Job,v['id']) for v in result['prepared_batches']]
                    self.assertEqual({batch_labels(j)['import_mode'] for j in jobs},{'manual','automatic'})
                    self.assertTrue(all(batch_labels(j)['display_code'][0] in ('M','A') for j in jobs))
                    target=jobs[1]
                    before=handoff(db,target)
                    self.assertTrue(before['batch_code'].startswith('BATCH-'))
                    self.assertTrue(before['display_code'].startswith('A-'))
                    withdraw_import(db,target.id,'验收模拟自动采集批次撤回')
                    after=dashboard(db,14)
                    self.assertEqual(after['total_papers'],508)
                    self.assertEqual(sum(v['papers'] for v in after['trend']),508)
                    for point in after['trend']:
                        self.assertEqual(sum(point['import_modes'].values()),point['papers'])
                    self.assertEqual(handoff(db,target)['batch_code'],before['batch_code'])
                    self.assertEqual(handoff(db,target)['exported_papers'],8)
            finally:factory.kw['bind'].dispose()
