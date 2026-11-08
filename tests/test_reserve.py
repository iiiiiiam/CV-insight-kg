import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from app.models import database,Source,Job,Paper,ImportCandidate
from app.ingest import run_job,openalex_work_row,upsert_paper
from app.reserve import stage_openalex,summary,queue_import
from tests.test_a_operations import work

class ReserveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.factory=database('sqlite:///'+str(self.path/'db.sqlite'))
        with self.factory() as db:db.add(Source(name='openalex'));db.commit()
        self.input=self.path/'papers.jsonl'
        self.input.write_text(''.join(json.dumps(work(i))+'\n' for i in range(1,8)))
    def tearDown(self):self.factory.kw['bind'].dispose();self.tmp.cleanup()
    def test_staging_and_successive_imports_really_add_new_papers(self):
        with self.factory() as db:
            upsert_paper(db,openalex_work_row(work(1),'CVPR',2024),'openalex');db.commit()
            stage_openalex(db,self.input,'CVPR',2024)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),1)
            self.assertEqual(summary(db)['available'],6)
            first,n=queue_import(db,'CVPR',2024,'openalex',2);self.assertEqual(n,2)
            self.assertEqual(summary(db)['available'],4)
            with patch('scripts.fetch_openalex_batch.fetch_batch') as network:run_job(db,first);network.assert_not_called()
            self.assertEqual((first.status,first.succeeded),('succeeded',2))
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),3)
            second,n=queue_import(db,'CVPR',2024,'openalex',2);run_job(db,second)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),5)
            self.assertEqual(summary(db)['available'],2)
            last,n=queue_import(db,'CVPR',2024,'openalex',20);self.assertEqual(n,2);run_job(db,last)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),7)
            self.assertEqual(summary(db)['available'],0)
            with self.assertRaises(ValueError):queue_import(db,'CVPR',2024,'openalex',20)
    def test_repeat_staging_and_conflicting_job_cannot_claim_twice(self):
        with self.factory() as db:
            stage_openalex(db,self.input,'CVPR',2024)
            self.assertEqual(stage_openalex(db,self.input,'CVPR',2024)['staged'],0)
            first,_=queue_import(db,'CVPR',2024,'openalex',2)
            with self.assertRaises(IntegrityError):queue_import(db,'CVPR',2024,'openalex',2)
            self.assertEqual(summary(db)['available'],5)
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(ImportCandidate).where(ImportCandidate.claimed_job_id==first.id)),2)
    def test_bad_scope_does_not_leave_partial_staged_data(self):
        bad=work(9);bad['publication_year']=2023
        self.input.write_text(json.dumps(work(1))+'\n'+json.dumps(bad)+'\n')
        with self.factory() as db:
            with self.assertRaises(ValueError):stage_openalex(db,self.input,'CVPR',2024)
            self.assertEqual(db.scalar(select(func.count()).select_from(ImportCandidate)),0)
