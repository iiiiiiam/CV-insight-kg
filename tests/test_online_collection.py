"""Bounded live imports: real DB and B module, HTTP only mocked at the source."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from datetime import timedelta
import requests
from sqlalchemy import select,func
from tests import test_formal_api
from tests.test_formal_batches import record
from app.models import Job,Paper,JobRecord,OnlineCollection,WorkflowTask,Source,now
from app.online_collection import process_online,online_view
from app.workflow_tasks import run_one
from app.auto_handoff import scan
from app.formal_batches import withdraw_batch
from src.knowledge_builder.batches import BatchRegistry


def work(number,year=2025,**extra):
 raw=record(number)['row']['raw'];raw['publication_year']=year
 raw.update({'topics':[],'primary_topic':None,'keywords':[],'ids':{'openalex':raw['id']},'locations':[],'best_oa_location':None})
 raw.update(extra);return raw


def http_page(rows):
 http=Mock();response=Mock();response.raise_for_status.return_value=None
 response.json.return_value={'results':rows,'meta':{'count':len(rows)}}
 http.get.return_value=response;return http


class OnlineTests(unittest.TestCase):
 def setUp(self):
  test_formal_api.FormalApiTests.setUp(self)
  self.temp=tempfile.TemporaryDirectory()
  self.env2=patch.dict(os.environ,{'A_AUTO_HANDOFF':'true','A_B_TRANSPORT':'local','B_BATCH_REGISTRY':str(Path(self.temp.name)/'b.json')})
  self.env2.start()
 def tearDown(self):
  self.env2.stop();self.temp.cleanup();test_formal_api.FormalApiTests.tearDown(self)
 def create(self,key='first',count=2,**extra):
  response=self.client.post('/api/admin/online-collections',headers=self.auth,
   json={'request_key':key,'venue':'CVPR','year':2025,'count':count,**extra})
  self.assertEqual(response.status_code,202,response.text);return response.json()
 def process(self,identifier,http):
  with self.factory() as db:process_online(db,db.get(Job,identifier),http=http)
 def detail(self,identifier):return self.client.get(f'/api/admin/online-collections/{identifier}',headers=self.auth).json()
 def test_auth_idempotency_input_limit_and_source_disable(self):
  self.assertEqual(self.client.post('/api/admin/online-collections',json={}).status_code,401)
  first=self.create();self.assertEqual(self.create()['id'],first['id'])
  self.assertEqual(self.client.post('/api/admin/online-collections',headers=self.auth,json={'request_key':'first','count':3}).status_code,409)
  self.assertEqual(self.client.post('/api/admin/online-collections',headers=self.auth,json={'count':51}).status_code,422)
  self.assertEqual(self.client.post('/api/admin/online-collections',headers=self.auth,json={'venue':'ICCV','year':2024}).status_code,409)
  with self.factory() as db:
   db.scalar(select(Source).where(Source.name=='openalex')).enabled=False;db.commit()
  self.assertEqual(self.client.post('/api/admin/online-collections',headers=self.auth,json={'year':2023}).status_code,409)
 def test_successive_requests_import_new_papers_and_call_integrated_b_without_http(self):
  first=self.create();http=http_page([work(1),work(2),work(3)])
  self.process(first['id'],http)
  detail=self.detail(first['id'])
  self.assertEqual((detail['status'],detail['imported_count'],detail['new_count']),('succeeded',2,2))
  self.assertEqual(http.get.call_args.kwargs['params']['filter'],'primary_location.source.id:S4210176548,publication_year:2025,has_abstract:true')
  with patch('app.delivery.requests.Session',side_effect=AssertionError('Integrated flow must not make B HTTP calls')):
   self.assertTrue(run_one(self.factory))
  self.assertEqual(BatchRegistry(Path(self.temp.name)/'b.json').snapshot()['paper_count'],2)
  second=self.create('second');self.process(second['id'],http_page([work(1),work(2),work(3)]))
  self.assertEqual(self.detail(second['id'])['imported_count'],1)
  self.assertEqual(self.detail(second['id'])['existing_count'],2)
  run_one(self.factory)
  with self.factory() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),3)
  self.assertEqual(BatchRegistry(Path(self.temp.name)/'b.json').snapshot()['paper_count'],3)
  with self.factory() as db:withdraw_batch(db,second['id'],'withdraw online batch')
  run_one(self.factory);self.assertEqual(BatchRegistry(Path(self.temp.name)/'b.json').snapshot()['paper_count'],2)
 def test_live_failure_does_not_fall_back_to_prepared_samples_and_retry_resumes_page(self):
  first=self.create(count=3)
  with self.factory() as db:
   source=db.scalar(select(Source).where(Source.name=='openalex'));source.max_retries=1;source.page_size=2;db.commit()
  http=http_page([work(1),work(2)])
  response=http.get.return_value
  http.get.side_effect=[response,requests.ConnectionError('offline')]
  with self.assertRaises(ValueError):self.process(first['id'],http)
  with self.factory() as db:
   self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),0)
   job=db.get(Job,first['id']);job.status='failed';job.active_key=None
   from app.auto_handoff import schedule_import_retry
   schedule_import_retry(job,db);job.next_retry_at=now()-timedelta(seconds=1);db.commit();scan(db)
   self.assertEqual(job.status,'queued');self.assertEqual(job.retry_attempts,1)
  second_http=http_page([work(3)]);self.process(first['id'],second_http)
  self.assertEqual(second_http.get.call_args.kwargs['params']['page'],2)
  self.assertEqual(self.detail(first['id'])['imported_count'],3)
 def test_bad_scope_and_missing_text_are_filtered_before_import(self):
  first=self.create(count=1)
  bad=work(9);bad['primary_location']['source']['id']='https://openalex.org/S1'
  self.process(first['id'],http_page([bad,work(8,2024),work(7,abstract_inverted_index=None),work(1)]))
  d=self.detail(first['id']);self.assertEqual(d['imported_count'],1);self.assertEqual(d['skipped_count'],3)
 def test_no_new_papers_completes_without_creating_empty_b_batch(self):
  first=self.create();self.process(first['id'],http_page([]))
  d=self.detail(first['id']);self.assertEqual((d['status'],d['stage'],d['imported_count']),('succeeded','unchanged',0))
  with self.factory() as db:self.assertEqual(db.scalar(select(func.count()).select_from(WorkflowTask)),0)
 def test_frozen_import_retry_does_not_repeat_source_request(self):
  first=self.create()
  from app.formal_batches import upsert_paper
  def fail_one(db,row,*args,**kwargs):
   if row['source_id'].endswith('W2'):raise ValueError('Temporary import failure')
   return upsert_paper(db,row,*args,**kwargs)
  with patch('app.formal_batches.upsert_paper',side_effect=fail_one):self.process(first['id'],http_page([work(1),work(2)]))
  self.assertEqual(self.detail(first['id'])['status'],'partial')
  blocked=Mock();blocked.get.side_effect=AssertionError('Input already frozen')
  self.process(first['id'],blocked);blocked.get.assert_not_called()
  with self.factory() as db:
   rows=db.scalars(select(JobRecord).where(JobRecord.job_id==first['id']).order_by(JobRecord.id)).all()
   self.assertEqual([r.attempts for r in rows],[1,2])
  self.assertEqual(self.detail(first['id'])['imported_count'],2)
