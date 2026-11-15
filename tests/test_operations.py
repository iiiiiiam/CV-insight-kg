import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import select
import unittest
from tests import test_formal_api as formal_tests
from tests.test_formal_batches import record
from app.models import Job,Paper,database
from app.formal_batches import process_batch

class OperationsTests(unittest.TestCase):
 setUp=formal_tests.FormalApiTests.setUp
 tearDown=formal_tests.FormalApiTests.tearDown
 def test_receipts_bind_revision_and_do_not_invent_downstream_success(self):
  result=self.client.post('/api/admin/formal/batches',headers=self.auth,json={'batch_key':'receipt','venue':'CVPR','year':2024,'records':[record(1)]}).json();identifier=result['batch_id']
  with self.factory() as db:process_batch(db,db.get(Job,identifier))
  route=f'/api/admin/formal/batches/{identifier}/receipts'
  current=self.client.get(route,headers=self.auth).json();self.assertEqual(current['items'],[])
  body={'batch_revision':current['batch_revision'],'status':'processed','snapshot_revision':'test-only-snapshot'}
  self.assertEqual(self.client.post(route,json=body).status_code,401)
  result=self.client.post(route,headers=self.auth,json=body).json();self.assertTrue(result['items'][0]['current'])
  self.assertEqual(self.client.post(route,headers=self.auth,json={**body,'status':'received'}).status_code,409)
  self.client.post(f'/api/admin/formal/batches/{identifier}/withdraw',headers=self.auth,json={'reason':'test withdrawal'})
  self.assertEqual(self.client.post(route,headers=self.auth,json=body).status_code,409)
  self.assertFalse(self.client.get(route,headers=self.auth).json()['items'][0]['current'])
 def test_quality_shows_real_missing_fields_and_requires_auth(self):
  from app.ingest import upsert_paper
  with self.factory() as db:upsert_paper(db,record(1,abstract_inverted_index=None,doi=None)['row'],'openalex');db.commit()
  self.assertEqual(self.client.get('/api/admin/quality').status_code,401)
  with patch('app.operations.load_baseline',side_effect=ValueError('test corrupt baseline')):
   report=self.client.get('/api/admin/quality',headers=self.auth).json()
  self.assertEqual(report['total_papers'],1);self.assertEqual(report['issues'][0]['missing'],['abstract','doi'])
 def test_records_auth_filter_page_and_failure_details(self):
  from app.models import JobRecord
  with self.factory() as db:
   job=Job(venue='CVPR',year=2024,source='openalex',status='failed');db.add(job);db.flush();identifier=job.id
   db.add_all([JobRecord(job_id=identifier,source='openalex',source_id=str(i),payload_json='{}',status='failed' if i<2 else 'succeeded',attempts=2,error='Network failure' if i<2 else None) for i in range(3)]);db.commit()
  route=f'/api/admin/jobs/{identifier}/records'
  self.assertEqual(self.client.get(route).status_code,401)
  result=self.client.get(route+'?status=failed&page=2&page_size=1',headers=self.auth).json()
  self.assertEqual(result['total'],2);self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['attempts'],2);self.assertEqual(result['items'][0]['error'],'Network failure')
  self.assertNotIn('payload_json',result['items'][0])
  self.assertEqual(self.client.get(route+'?status=other',headers=self.auth).status_code,422)
  self.assertEqual(self.client.get('/api/admin/jobs/999999/records',headers=self.auth).status_code,404)

 def test_legacy_cvf_records_are_readable(self):
  from app.models import CvfRecord
  with self.factory() as db:
   job=Job(venue='CVPR',year=2024,source='cvf',status='partial');db.add(job);db.flush();identifier=job.id
   db.add(CvfRecord(job_id=identifier,source_id='legacy-paper',payload='{}',status='failed'));db.commit()
  data=self.client.get(f'/api/admin/jobs/{identifier}/records?status=failed',headers=self.auth).json()
  self.assertEqual(data['total'],1);self.assertEqual(data['items'][0]['source'],'cvf');self.assertIsNone(data['items'][0]['attempts'])
