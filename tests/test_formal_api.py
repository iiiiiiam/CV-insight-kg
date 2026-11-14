import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models import Base,Job
from app.api import app,db_session
from app.db import seed_sources
from app.formal_batches import process_batch
from tests.test_formal_batches import record


class FormalApiTests(unittest.TestCase):
 def setUp(self):
  self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool);Base.metadata.create_all(self.engine);self.factory=sessionmaker(self.engine,expire_on_commit=False)
  def sessions():
   with self.factory() as db:yield db
  app.dependency_overrides[db_session]=sessions
  self.env=patch.dict(os.environ,{'ADMIN_TOKEN':'formal-test','LOCAL_DEMO':'0'});self.env.start()
  self.seed=patch('app.api.seed_sources',lambda:seed_sources(self.factory));self.seed.start()
  self.client=TestClient(app);self.client.__enter__();self.auth={'Authorization':'Bearer formal-test'}
 def tearDown(self):
  self.client.__exit__(None,None,None);self.seed.stop();self.env.stop();app.dependency_overrides.clear();self.engine.dispose()
 def test_existing_auth_boundary_covers_new_read_and_write_endpoints(self):
  payload={'batch_key':'api','venue':'CVPR','year':2024,'records':[record(1)]}
  self.assertEqual(self.client.post('/api/admin/formal/batches',json=payload).status_code,401)
  self.assertEqual(self.client.get('/api/admin/formal/batches').status_code,401)
  response=self.client.post('/api/admin/formal/batches',json=payload,headers=self.auth);self.assertEqual(response.status_code,201)
  identifier=response.json()['batch_id']
  listing=self.client.get('/api/admin/formal/batches',headers=self.auth).json()
  self.assertEqual(listing['total'],1);self.assertEqual(listing['items'][0]['batch_key'],'api')
  self.assertEqual(self.client.get('/api/admin/formal/effective',headers=self.auth).status_code,409)
  self.assertEqual(self.client.get('/api/admin/formal/effective').status_code,401)
  self.assertEqual(self.client.post(f'/api/admin/formal/batches/{identifier}/withdraw',json={'reason':'test'}).status_code,401)
  with self.factory() as db:process_batch(db,db.get(Job,identifier))
  state=self.client.get('/api/admin/formal/effective',headers=self.auth).json();self.assertEqual(state['paper_count'],1)
  original=self.client.get(f'/api/admin/handoff?batch_id={identifier}',headers=self.auth).json();self.assertEqual(original['format_version'],'a-paperinput/1');self.assertEqual(original['counts']['added'],1)
  self.assertEqual(self.client.post('/api/admin/formal/batches',json=payload,headers=self.auth).json()['replay'],True)
  withdrawn=self.client.post(f'/api/admin/formal/batches/{identifier}/withdraw',json={'reason':'Requested withdrawal'},headers=self.auth).json();self.assertEqual(withdrawn['state'],'withdrawn')
  self.assertEqual(self.client.get('/api/admin/formal/effective',headers=self.auth).json()['paper_count'],0)
  self.assertEqual(self.client.get('/api/papers').json()['total'],0)
  payload['records']=[record(2)]
  self.assertEqual(self.client.post('/api/admin/formal/batches',json=payload,headers=self.auth).status_code,422)
 def test_missing_batch_and_blank_reason_do_not_write(self):
  self.assertEqual(self.client.get('/api/admin/formal/batches/999',headers=self.auth).status_code,404)
  self.assertEqual(self.client.post('/api/admin/formal/batches/999/withdraw',headers=self.auth,json={'reason':' '}).status_code,404)
 def test_withdrawn_batch_keeps_its_frozen_papers_quality_and_comparison(self):
  def ingest(key,records):
   result=self.client.post('/api/admin/formal/batches',headers=self.auth,json={'batch_key':key,'venue':'CVPR','year':2024,'records':records})
   self.assertEqual(result.status_code,201)
   identifier=result.json()['batch_id']
   with self.factory() as db:process_batch(db,db.get(Job,identifier))
   return identifier
  first=ingest('first',[record(1),record(2)])
  second=ingest('second',[record(2,cited_by_count=99),record(3)])
  self.client.post(f'/api/admin/formal/batches/{second}/withdraw',headers=self.auth,json={'reason':'test rollback'})
  self.assertEqual(self.client.get('/api/papers').json()['total'],2)
  listing=self.client.get('/api/admin/jobs',headers=self.auth).json()
  self.assertEqual((listing[0]['id'],listing[0]['batch_state']),(second,'withdrawn'))
  detail=self.client.get(f'/api/admin/jobs/{second}',headers=self.auth).json()
  self.assertEqual(detail['source_names'],['openalex']);self.assertEqual(detail['paper_count'],2);self.assertEqual(detail['quality']['total'],2)
  papers=self.client.get(f'/api/admin/jobs/{second}/papers',headers=self.auth).json()
  self.assertEqual(papers['total'],2)
  self.assertEqual(papers['items'][0]['cited_by_count'],99)
  filtered=self.client.get(f'/api/admin/jobs/{second}/papers?q=Paper%203&page_size=1',headers=self.auth).json()
  self.assertEqual(filtered['total'],1);self.assertEqual(filtered['items'][0]['title'],'Research Paper 3')
  comparison=self.client.get(f'/api/admin/batch-comparison?first={first}&second={second}',headers=self.auth).json()
  self.assertEqual((comparison['shared_papers'],comparison['only_first'],comparison['only_second']),(1,1,1))
