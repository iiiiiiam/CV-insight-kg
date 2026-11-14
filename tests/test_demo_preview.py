"""A small preview must retain a usable, genuine import workflow."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import select

from app.demo import create_demo
from app.data_overview import dashboard
from app.ingest import run_job
from app.models import ImportCandidate, Job, Source, database
from app.reserve import queue_import, stage_openalex, summary
from tests.test_a_operations import work


class PreviewTests(unittest.TestCase):
    def test_small_continuous_preview_retains_all_candidates_and_real_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            old=root/'previous.db'
            previous=database('sqlite:///'+str(old))
            try:
                with previous() as db:
                    db.add(Source(name='openalex'));db.commit()
                    pool=root/'pool.jsonl'
                    pool.write_text(''.join(json.dumps(work(i))+'\n' for i in range(1,8)))
                    stage_openalex(db,pool,'CVPR',2024)
                    job=Job(venue='CVPR',year=2024,source='openalex',kind='reserve',status='succeeded')
                    db.add(job);db.flush()
                    old_claim=job.id
                    for candidate in db.scalars(select(ImportCandidate)):
                        candidate.claimed_job_id=job.id
                    db.commit()
                    source_ids=set(db.scalars(select(ImportCandidate.source_id)))
                target=root/'preview.db'
                create_demo(target,reserve_db=old)
                factory=database('sqlite:///'+str(target))
                try:
                    with factory() as db:
                        overview=dashboard(db,14)
                        self.assertEqual(overview['total_papers'],420)
                        self.assertEqual(len(overview['trend']),14)
                        self.assertTrue(all(0<p['papers']<100 for p in overview['trend']))
                        self.assertEqual(sum(p['papers'] for p in overview['trend']),420)
                        for point in overview['trend']:
                            self.assertEqual(sum(point['sources'].values()),point['papers'])
                            self.assertEqual(point['import_modes'],{'manual':12,'automatic':18})
                        retained=list(db.scalars(select(ImportCandidate).where(ImportCandidate.source_id.in_(source_ids))))
                        self.assertEqual(len(retained),7)
                        self.assertTrue(all(c.claimed_job_id is None for c in retained))
                        available=summary(db)['available']
                        self.assertGreater(available,2000)
                        job,count=queue_import(db,'CVPR',2024,'openalex',20)
                        with patch('scripts.fetch_openalex_batch.fetch_batch') as network:
                            run_job(db,job);network.assert_not_called()
                        self.assertEqual((count,job.status,job.succeeded),(20,'succeeded',20))
                        after=dashboard(db,14)
                        self.assertEqual(after['total_papers'],440)
                        self.assertEqual(after['today_papers'],overview['today_papers']+20)
                        self.assertEqual(summary(db)['available'],available-20)
                    with self.assertRaises(ValueError):create_demo(target)
                finally:factory.kw['bind'].dispose()
                with previous() as db:
                    self.assertEqual(set(db.scalars(select(ImportCandidate.claimed_job_id))),{old_claim})
            finally:previous.kw['bind'].dispose()
