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
    def test_demo_history_rolls_without_writing_dates(self):
        from datetime import timedelta
        from unittest.mock import patch
        from app.models import now,Paper
        from app.data_activity import additions
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'preview.db'
            create_demo(path)
            factory=database('sqlite:///'+str(path))
            try:
                with factory() as db:
                    original={p.id:p.first_seen_at for p in db.scalars(select(Paper))}
                    future=now()+timedelta(days=40)
                    with patch('app.models.now',return_value=future),patch('app.data_overview.now',return_value=future):
                        report=dashboard(db,14)
                        self.assertTrue(all(p['added_papers']>0 for p in report['trend']))
                        for point in report['trend']:
                            self.assertEqual(point['added_papers'],sum(p['first_seen_at'].date().isoformat()==point['date'] for p in additions(db)))
                    self.assertEqual(original,{p.id:p.first_seen_at for p in db.scalars(select(Paper))})
            finally:factory.kw['bind'].dispose()

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
