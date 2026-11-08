import unittest
from unittest.mock import patch
from sqlalchemy import select
from app.models import database, Job, Source, Paper, PaperBatch, CvfRecord
from app.cvf_job import run_cvf_job
from app.data_overview import handoff

ROW = {'source_id':'cvf:test', 'source_url':'https://openaccess.thecvf.com/content/CVPR2024/html/test_paper.html', 'venue':'CVPR','year':2024,'authors':['Test Author'],'title':'Example Paper','raw':{}}
WORK = {'id':'https://openalex.org/W123', 'display_name':'Example Paper','publication_year':2024,'authorships':[], 'primary_location':{'source':{'id':'https://openalex.org/S4210176548'}}}

class CVFJobTest(unittest.TestCase):
    def setUp(self):
        self.factory = database('sqlite:///:memory:')
        self.db = self.factory()
        self.db.add(Source(name='cvf',enabled=True,max_retries=1))
        self.job = Job(venue='CVPR',year=2024,source='cvf',dataset_id='cvf:1:1',active_key='CVPR:2024')
        self.db.add(self.job); self.db.commit()
    def tearDown(self):
        self.db.close(); self.factory.kw['bind'].dispose()
    @patch('app.cvf_job.match_openalex', return_value=WORK)
    @patch('app.cvf_job.cvf.fetch_detail', return_value={**ROW,'abstract':'A real abstract.'})
    @patch('app.cvf_job.cvf.fetch_index', return_value=[ROW])
    def test_import_handoff_retry(self, index, detail, match):
        run_cvf_job(self.db,self.job)
        self.assertEqual((self.job.status,self.job.succeeded,self.job.failed),('succeeded',1,0))
        result = handoff(self.db,self.job)
        self.assertEqual(result['exported_papers'],1)
        self.assertEqual(result['items'][0]['openalex_id'], WORK['id'])
        self.assertEqual(result['items'][0]['abstract'],'A real abstract.')
        self.assertTrue(self.db.scalar(select(PaperBatch)).is_new)
        run_cvf_job(self.db,self.job)
        self.assertEqual(index.call_count,1)
        self.assertEqual(detail.call_count,1)
        self.assertEqual(len(self.db.scalars(select(Paper)).all()),1)
    @patch('app.cvf_job.match_openalex', return_value=None)
    @patch('app.cvf_job.cvf.fetch_detail', return_value={**ROW,'abstract':'Real abstract.'})
    @patch('app.cvf_job.cvf.fetch_index', return_value=[ROW])
    def test_missing_match_excluded(self, *_):
        run_cvf_job(self.db,self.job)
        self.assertEqual(handoff(self.db,self.job)['excluded_papers'],1)
    @patch('app.cvf_job.match_openalex', return_value=WORK)
    @patch('app.cvf_job.cvf.fetch_detail', side_effect=[ValueError('temporary'),{**ROW,'abstract':'Real abstract.'}])
    @patch('app.cvf_job.cvf.fetch_index', return_value=[ROW])
    def test_failed_record_retries_same_snapshot(self, index, *_):
        run_cvf_job(self.db,self.job)
        self.assertEqual(self.job.status,'partial')
        run_cvf_job(self.db,self.job)
        self.assertEqual((self.job.status,self.job.succeeded,self.job.failed),('succeeded',1,0))
        self.assertEqual(index.call_count,1)
        self.assertEqual(self.db.scalar(select(CvfRecord)).status,'succeeded')
