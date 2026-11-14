import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select,delete

from app.api import app,db_session
from app.batch_withdrawal import withdraw_import,withdrawal_state
from app.data_overview import dashboard,handoff,batch_summary
from app.db import seed_sources
from app.formal_batches import queue_batch,process_batch,withdraw_batch
from app.ingest import run_job,openalex_work_row
from app.models import BatchLedger,Job,Paper,PaperBatch,StablePaper,database
from app.reserve import queue_import,stage_openalex,summary
from tests.test_a_operations import work


class ManualWithdrawalTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();root=Path(self.temporary.name)
        self.factory=database('sqlite:///'+str(root/'test.db'));seed_sources(self.factory)
        path=root/'papers.jsonl';path.write_text(''.join(json.dumps(work(i))+'\n' for i in range(1,8)))
        with self.factory() as db:stage_openalex(db,path,'CVPR',2024)

    def tearDown(self):
        self.factory.kw['bind'].dispose();self.temporary.cleanup()

    def imported(self,db,count=3,legacy=False):
        job,_=queue_import(db,'CVPR',2024,'openalex',count)
        if legacy:
            db.execute(delete(BatchLedger).where(BatchLedger.job_id==job.id));db.commit()
        run_job(db,job)
        self.assertEqual(job.status,'succeeded')
        return job

    def test_withdraw_keeps_history_releases_pool_and_reimport_preserves_ids(self):
        with self.factory() as db:
            job=self.imported(db)
            ids=list(db.scalars(select(Paper.id).order_by(Paper.id)))
            stable=list(db.scalars(select(StablePaper.stable_id).order_by(StablePaper.paper_id)))
            self.assertEqual((dashboard(db)['total_papers'],summary(db)['available']),(3,4))
            result=withdraw_import(db,job.id,'撤回测试')
            self.assertEqual(result['state'],'withdrawn')
            self.assertEqual((dashboard(db)['total_papers'],summary(db)['available']),(0,7))
            self.assertEqual(batch_summary(db,job)['paper_count'],3)
            self.assertEqual(handoff(db,job)['exported_papers'],3)
            self.assertEqual(withdraw_import(db,job.id,'再点一次')['withdrawn_at'],result['withdrawn_at'])
            second=self.imported(db)
            self.assertNotEqual(second.id,job.id)
            self.assertEqual(list(db.scalars(select(Paper.id).order_by(Paper.id))),ids)
            self.assertEqual(list(db.scalars(select(StablePaper.stable_id).order_by(StablePaper.paper_id))),stable)
            self.assertEqual((dashboard(db)['total_papers'],summary(db)['available']),(3,4))

    def shared_sequence(self,legacy):
        with self.factory() as db:
            manual=self.imported(db,legacy=legacy)
            rows=[{'source':'openalex','row':openalex_work_row(work(i),'CVPR',2024)} for i in (2,4)]
            later,_=queue_batch(db,'later','CVPR',2024,rows);process_batch(db,later)
            self.assertEqual(dashboard(db)['total_papers'],4)
            withdraw_import(db,manual.id,'撤回手动批次')
            self.assertEqual(dashboard(db)['total_papers'],2)
            self.assertEqual(handoff(db,manual)['exported_papers'],3)
            withdraw_batch(db,later.id,'撤回共享批次')
            self.assertEqual(dashboard(db)['total_papers'],0)

    def test_shared_later_batch_survives_manual_withdrawal(self):
        self.shared_sequence(False)

    def test_old_manual_import_and_shared_later_batch_can_both_be_withdrawn(self):
        self.shared_sequence(True)

    def test_active_tasks_and_blank_reasons_do_not_change_data(self):
        with self.factory() as db:
            job,_=queue_import(db,'CVPR',2024,'openalex',3)
            self.assertFalse(withdrawal_state(db,job.id)['can_withdraw'])
            with self.assertRaises(ValueError):withdraw_import(db,job.id,'尚在导入')
            run_job(db,job)
            with self.assertRaises(ValueError):withdraw_import(db,job.id,'   ')
            pending,_=queue_import(db,'CVPR',2024,'openalex',1)
            with self.assertRaises(ValueError):withdraw_import(db,job.id,'其他任务运行中')
            self.assertEqual(dashboard(db)['total_papers'],3)
            run_job(db,pending)
            self.assertTrue(withdrawal_state(db,job.id)['can_withdraw'])

    def test_paper_provided_by_an_older_style_import_is_retained(self):
        with self.factory() as db:
            manual=self.imported(db)
            another=Job(venue='CVPR',year=2024,source='openalex',kind='sample',status='succeeded')
            db.add(another);db.flush()
            paper=db.scalar(select(Paper).order_by(Paper.id))
            db.add(PaperBatch(job_id=another.id,paper_id=paper.id,is_new=False));db.commit()
            withdraw_import(db,manual.id,'保留另一批次提供的论文')
            self.assertEqual(dashboard(db)['total_papers'],1)
            self.assertEqual(db.scalar(select(Paper.id).where(Paper.id==paper.id)),paper.id)

    def test_api_preserves_history_and_rejects_retry_after_withdrawal(self):
        def sessions():
            with self.factory() as db:yield db
        app.dependency_overrides[db_session]=sessions
        try:
            with patch.dict(os.environ,{'ADMIN_TOKEN':'manual-test','LOCAL_DEMO':'0'}),patch('app.api.seed_sources',lambda:seed_sources(self.factory)),TestClient(app) as client:
                auth={'Authorization':'Bearer manual-test'}
                with self.factory() as db:job=self.imported(db,legacy=True);identifier=job.id
                endpoint=f'/api/admin/jobs/{identifier}'
                self.assertEqual(client.post(endpoint+'/withdraw',json={'reason':'测试'}).status_code,401)
                self.assertEqual(client.get(endpoint+'/withdrawal',headers=auth).json()['can_withdraw'],True)
                self.assertEqual(client.post(endpoint+'/withdraw',headers=auth,json={'reason':'   '}).status_code,409)
                self.assertEqual(client.post(endpoint+'/withdraw',headers=auth,json={'reason':'测试'}).json()['state'],'withdrawn')
                self.assertEqual(client.get(endpoint,headers=auth).json()['batch_state'],'withdrawn')
                self.assertEqual(client.get(endpoint+'/papers',headers=auth).json()['total'],3)
                self.assertEqual(client.get(f'/api/admin/handoff?batch_id={identifier}',headers=auth).json()['exported_papers'],3)
                self.assertEqual(client.get('/api/papers').json()['total'],0)
                with self.factory() as db:db.get(Job,identifier).status='partial';db.commit()
                self.assertEqual(client.post(endpoint+'/retry',headers=auth).status_code,409)
        finally:app.dependency_overrides.clear()
