import json
import os
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api import app,db_session
from app.batch_withdrawal import withdraw_import
from app.data_activity import withdrawal_events
from app.data_overview import dashboard
from app.db import seed_sources
from app.formal_batches import queue_batch,process_batch,withdraw_batch
from app.ingest import openalex_work_row,run_job
from app.models import Job,Paper,PaperBatch,database,now
from app.reserve import queue_import,stage_openalex
from tests.test_a_operations import work


class DataActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.factory=database('sqlite:///'+str(root/'test.db'));seed_sources(self.factory)
        path=root/'input.jsonl';path.write_text(''.join(json.dumps(work(i))+'\n' for i in range(1,8)))
        with self.factory() as db:stage_openalex(db,path,'CVPR',2024)

    def tearDown(self):self.factory.kw['bind'].dispose();self.tmp.cleanup()

    def manual(self,db,count):
        job,_=queue_import(db,'CVPR',2024,'openalex',count);run_job(db,job);return job

    def test_additions_remain_on_original_day_withdrawal_is_on_execution_day(self):
        with self.factory() as db:
            job=self.manual(db,3);identifier=job.id
            old=now()-timedelta(days=2);old_date=old.date().isoformat();today=now().date().isoformat()
            for membership in db.scalars(select(PaperBatch).where(PaperBatch.job_id==identifier)):
                membership.imported_at=old;db.get(Paper,membership.paper_id).first_seen_at=old
            db.commit()
            before=dashboard(db,14)
            withdraw_import(db,identifier,'撤回历史导入')
            after=dashboard(db,14)
            original=next(p for p in after['trend'] if p['date']==old_date)
            self.assertEqual((original['papers'],original['added_papers']),(0,3))
            current=next(p for p in after['trend'] if p['date']==today)
            self.assertEqual((current['withdrawn_papers'],current['withdrawn_batches'],current['net_papers']),(3,1,-3))
            self.assertEqual(after['today_withdrawn_papers'],3)
            self.assertEqual(sum(p['added_papers'] for p in before['trend']),sum(p['added_papers'] for p in after['trend']))
            self.manual(db,3)
            self.assertEqual(withdrawal_events(db)[0]['removed_papers'],3)
            withdraw_import(db,identifier,'重复撤回')
            final=dashboard(db,14)
            self.assertEqual((final['total_papers'],final['today_withdrawn_papers']),(3,3))
            self.assertEqual(sum(p['added_papers'] for p in final['trend']),6)
            self.assertEqual(next(p for p in final['trend'] if p['date']==old_date)['added_papers'],3)

    def test_shared_papers_are_retained_and_not_counted_as_removed(self):
        with self.factory() as db:
            first=self.manual(db,2)
            records=[{'source':'openalex','row':openalex_work_row(work(i),'CVPR',2024)} for i in (2,3)]
            second,_=queue_batch(db,'shared','CVPR',2024,records);process_batch(db,second)
            withdraw_import(db,first.id,'撤回第一批')
            event=withdrawal_events(db)[0]
            self.assertEqual((event['removed_papers'],event['retained_papers']),(1,1))
            report=dashboard(db)
            self.assertEqual((report['today_added_papers'],report['today_withdrawn_papers'],report['today_net_papers']),(3,1,2))
            withdraw_batch(db,second.id,'撤回第二批')
            report=dashboard(db)
            self.assertEqual((report['total_papers'],report['today_added_papers'],report['today_withdrawn_papers']),(0,3,3))

    def test_daily_activity_endpoint_includes_withdrawn_history_and_batch_details(self):
        with self.factory() as db:
            job=self.manual(db,3);identifier=job.id;withdraw_import(db,identifier,'日趋势验收')
        def sessions():
            with self.factory() as db:yield db
        app.dependency_overrides[db_session]=sessions
        try:
            with patch.dict(os.environ,{'ADMIN_TOKEN':'activity-test','LOCAL_DEMO':'0'}),patch('app.api.seed_sources',lambda:seed_sources(self.factory)),TestClient(app) as client:
                path='/api/admin/new-papers?view=additions&day='+now().date().isoformat()
                auth={'Authorization':'Bearer activity-test'}
                self.assertEqual(client.get(path).status_code,401)
                value=client.get(path+'&page_size=2',headers=auth).json()
                self.assertEqual((value['total'],len(value['items']),value['withdrawn_papers'],value['net_papers']),(3,2,3,0))
                self.assertEqual(value['withdrawals'][0]['batch_id'],identifier)
                self.assertEqual(value['withdrawals'][0]['reason'],'日趋势验收')
                self.assertTrue(value['withdrawals'][0]['display_code'].startswith('M-'))
                self.assertEqual(client.get(path.replace('view=additions&',''),headers=auth).json()['total'],0)
        finally:app.dependency_overrides.clear()
