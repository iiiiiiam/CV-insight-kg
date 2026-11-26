"""Automatic delivery against a real isolated B registry; no external HTTP."""
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
from sqlalchemy import select,func,delete
from app.models import database,Job,JobRecord,WorkflowTask,HandoffReconciliation,Paper,now
from app.formal_batches import queue_batch,process_batch,batch_manifest,withdraw_batch
from app.auto_handoff import scan,maintain,reconcile
from app.workflow_tasks import run_one,recover
from src.knowledge_builder.batches import BatchRegistry
from tests.test_formal_batches import record


class AutoHandoffTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.factory=database('sqlite:///'+str(self.root/'a.db'));self.b=BatchRegistry(self.root/'b.json')
  self.env=patch.dict('os.environ',{'A_AUTO_HANDOFF':'true','B_API_BASE_URL':'http://b.test',
   'B_ADMIN_USERNAME':'fixture','B_ADMIN_PASSWORD':'fixture'})
  self.env.start();self.lost_response=False
  owner=self
  class Http:
   def __init__(self):self.headers={}
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def request(self,method,url,json=None,**kwargs):
    path=url.removeprefix('http://b.test')
    if path=='/api/admin/sessions':value={'csrf_token':'fixture'}
    elif method=='GET':value=owner.remote()
    elif path.endswith('/withdraw'):value=owner.b.withdraw(path.split('/')[-2],expected_revision=json['revision'])
    else:
     value=owner.b.ingest(json['document'],expected_revision=json['revision'])
     if owner.lost_response:
      owner.lost_response=False;raise requests.ConnectionError('simulated lost acknowledgement')
    return SimpleNamespace(status_code=200,json=lambda:value)
  self.http=patch('app.delivery.requests.Session',Http);self.http.start()
 def tearDown(self):
  self.http.stop();self.env.stop();self.factory.kw['bind'].dispose();self.temp.cleanup()
 def remote(self):
  state=self.b.read();snap=self.b.snapshot()
  return {'revision':state['revision'],'snapshot_revision':snap['revision'],'paper_count':snap['paper_count'],
   'batches':[dict(batch_id=b['batch_id'],batch_code=b['batch_code'],active=b['active'],handoff_digest=b['handoff_digest']) for b in state['batches']]}
 def ingest(self,key,rows=None):
  with self.factory() as db:
   job,_=queue_batch(db,key,'CVPR',2024,rows or [record(1)]);process_batch(db,job);return job.id
 def task(self,batch):
  with self.factory() as db:return db.scalar(select(WorkflowTask).where(WorkflowTask.batch_id==batch).order_by(WorkflowTask.created_at.desc()))
 def due_audit(self):
  with self.factory() as db:
   state=db.get(HandoffReconciliation,'B')
   if state:state.next_check_at=now()-timedelta(seconds=1);db.commit()
 def test_success_queues_once_and_restart_recovers_omission(self):
  batch=self.ingest('first');task=self.task(batch)
  self.assertTrue(task.automatic);self.assertEqual(task.status,'queued')
  with self.factory() as db:scan(db);self.assertEqual(db.scalar(select(func.count()).select_from(WorkflowTask)),1)
  run_one(self.factory);self.assertEqual(self.b.snapshot()['paper_count'],1)
  self.assertEqual(self.task(batch).status,'succeeded')
  with self.factory() as db:db.execute(delete(WorkflowTask));db.commit();scan(db)
  recover(self.factory);run_one(self.factory)
  self.assertEqual(self.b.snapshot()['paper_count'],1)
  self.assertEqual(self.task(batch).status,'succeeded')
 def test_failure_uses_backoff_and_stops_at_budget_then_manual_retry(self):
  batch=self.ingest('retry')
  with patch('app.delivery.send',side_effect=requests.ConnectionError('offline')):
   for attempt in range(5):
    self.assertTrue(run_one(self.factory))
    task=self.task(batch);self.assertEqual(task.status,'failed')
    self.assertFalse(run_one(self.factory))
    if attempt<4:
     self.assertIsNotNone(task.next_attempt_at)
     with self.factory() as db:db.get(WorkflowTask,task.id).next_attempt_at=now()-timedelta(seconds=1);db.commit()
  task=self.task(batch);self.assertIsNone(task.next_attempt_at);self.assertEqual(task.attempts,5)
  with self.factory() as db:scan(db)
  self.assertFalse(run_one(self.factory))
  from app.workflow_tasks import retry
  with self.factory() as db:retry(db,db.get(WorkflowTask,task.id))
  run_one(self.factory);self.assertEqual(self.task(batch).status,'succeeded')
 def test_lost_acknowledgement_reconciles_without_reingestion(self):
  batch=self.ingest('lost');self.lost_response=True
  run_one(self.factory);self.assertEqual(self.task(batch).status,'failed')
  self.assertEqual(len(self.b.read()['batches']),1)
  maintain(self.factory)
  task=self.task(batch);self.assertEqual(task.status,'succeeded');self.assertEqual(task.attempts,1)
  self.assertEqual(len(self.b.read()['batches']),1)
  with self.factory() as db:self.assertEqual(db.get(HandoffReconciliation,'B').status,'synchronized')
 def test_missing_b_database_is_repaired_automatically(self):
  batch=self.ingest('repair');run_one(self.factory);self.b.path.unlink()
  maintain(self.factory);self.assertEqual(self.task(batch).status,'queued')
  run_one(self.factory);self.assertEqual(self.b.snapshot()['paper_count'],1)
  self.assertEqual(self.task(batch).attempts,2)
 def test_stale_delivery_stops_and_withdrawal_survives_restart(self):
  batch=self.ingest('withdraw-before-send')
  with self.factory() as db:result=withdraw_batch(db,batch,'withdraw before worker');notification=result['b_notification']['id']
  run_one(self.factory)
  with self.factory() as db:
   old=db.scalar(select(WorkflowTask).where(WorkflowTask.batch_id==batch,WorkflowTask.id!=notification))
   self.assertFalse(old.retryable);self.assertIsNone(old.next_attempt_at)
  recover(self.factory);run_one(self.factory)
  self.assertEqual(self.b.snapshot()['paper_count'],0)
  with self.factory() as db:self.assertEqual(db.get(WorkflowTask,notification).status,'succeeded')
 def test_independent_b_withdrawal_is_conflict_and_not_revived(self):
  batch=self.ingest('conflict');run_one(self.factory)
  self.b.withdraw(f'BATCH-{batch:06d}')
  maintain(self.factory)
  with self.factory() as db:self.assertEqual(db.get(HandoffReconciliation,'B').status,'attention')
  self.assertEqual(self.b.snapshot()['paper_count'],0)
 def test_import_failure_retries_only_failed_rows_and_stops_after_three(self):
  from app.formal_batches import upsert_paper
  def fail_second(db,row,*args,**kwargs):
   if row['source_id'].endswith('W2'):raise ValueError('temporary failure')
   return upsert_paper(db,row,*args,**kwargs)
  with patch('app.formal_batches.upsert_paper',side_effect=fail_second):batch=self.ingest('partial',[record(1),record(2)])
  with self.factory() as db:
   job=db.get(Job,batch);self.assertEqual(job.status,'partial');self.assertIsNotNone(job.next_retry_at)
   self.assertEqual(db.scalar(select(func.count()).select_from(WorkflowTask)),0)
   job.next_retry_at=now()-timedelta(seconds=1);db.commit();scan(db)
   self.assertEqual(job.status,'queued');process_batch(db,job)
   rows=db.scalars(select(JobRecord).where(JobRecord.job_id==batch).order_by(JobRecord.id)).all()
   self.assertEqual([r.attempts for r in rows],[1,2]);self.assertEqual(job.status,'succeeded')
  self.assertEqual(self.task(batch).status,'queued')
 def test_annotations_are_consumed_without_another_openalex_request_and_restore_on_withdraw(self):
  from src.knowledge_builder.batch_sources import BatchSources
  from src.knowledge_builder.enrichment_sources import SourceUnavailable
  def annotated(topic):return record(1,topics=[{'id':'https://openalex.org/T1','display_name':topic}],
   primary_topic=None,keywords=[],ids={'openalex':'https://openalex.org/W1'},locations=[],best_oa_location=None)
  first=self.ingest('annotations-first',[annotated('Vision')]);run_one(self.factory)
  sources=BatchSources(self.b.path,offline=True,cache_path=self.root/'cache')
  papers=list(self.b.workspace(self.root/'feedback.json',source_store=sources).papers.values())
  client=Mock();client.openalex.side_effect=AssertionError('A provided annotations; do not fetch again')
  client.papers_with_code.side_effect=SourceUnavailable('Not part of this test')
  sources.prepare(papers,client=client);client.openalex.assert_not_called()
  before=sources.records(papers)[papers[0].openalex_id][0]['payload']['topics'][0]['display_name']
  self.assertEqual(before,'Vision')
  second=self.ingest('annotations-second',[annotated('Learning')]);run_one(self.factory)
  self.assertEqual(sources.records(papers)[papers[0].openalex_id][0]['payload']['topics'][0]['display_name'],'Learning')
  with self.factory() as db:withdraw_batch(db,second,'restore previous annotations')
  run_one(self.factory)
  self.assertEqual(sources.records(papers)[papers[0].openalex_id][0]['payload']['topics'][0]['display_name'],'Vision')
 def test_bad_upstream_annotation_is_rejected_atomically(self):
  batch=self.ingest('tamper',[record(1,topics=[],keywords=[])])
  with self.factory() as db:document=batch_manifest(db,batch)
  document['source_annotations'][0]['record']['digest']='0'*64
  self.assertEqual(self.b.ingest(document)['status'],'failed');self.assertEqual(self.b.snapshot()['paper_count'],0)

 def test_a_annotation_selection_covers_b_openalex_read_fields(self):
  from scripts.fetch_openalex_batch import FIELDS,ANNOTATION_FIELDS
  from src.knowledge_builder.enrichment_sources import OPENALEX_FIELDS
  self.assertLessEqual(set(OPENALEX_FIELDS.split(',')),set((FIELDS+','+ANNOTATION_FIELDS).split(',')))

 def test_import_retries_stop_after_three_and_keep_failed_batch_visible(self):
  with patch('app.formal_batches.upsert_paper',side_effect=ValueError('failure persists')):
   batch=self.ingest('persistent-import-failure')
   for attempt in range(1,4):
    with self.factory() as db:
     job=db.get(Job,batch);job.next_retry_at=now()-timedelta(seconds=1);db.commit()
     scan(db);self.assertEqual(job.status,'queued');process_batch(db,job)
     self.assertEqual(job.retry_attempts,attempt)
   with self.factory() as db:
    job=db.get(Job,batch);self.assertIsNone(job.next_retry_at);scan(db)
    self.assertEqual(job.status,'partial');self.assertEqual(job.retry_attempts,3)
    self.assertEqual(db.scalar(select(func.count()).select_from(WorkflowTask)),0)
 def test_unknown_same_code_b_batch_is_never_withdrawn(self):
  batch=self.ingest('local-first')
  with self.factory() as db:foreign=batch_manifest(db,batch)
  foreign['items'][0]['title']='A different paper from another database'
  self.assertEqual(self.b.ingest(foreign)['status'],'accepted')
  with self.factory() as db:withdraw_batch(db,batch,'withdraw local')
  run_one(self.factory);run_one(self.factory)
  self.assertEqual(self.b.snapshot()['paper_count'],1)
  task=self.task(batch);self.assertEqual(task.status,'failed');self.assertFalse(task.retryable)
  maintain(self.factory)
  with self.factory() as db:self.assertEqual(db.get(HandoffReconciliation,'B').status,'attention')
 def test_old_missing_batch_does_not_overwrite_newer_b_paper_metadata(self):
  first=self.ingest('first-version',[record(1)]);run_one(self.factory)
  second=self.ingest('newer-version',[record(1,display_name='Updated paper title')]);run_one(self.factory)
  newer=self.b.read()['batches'][-1]['document'];self.b.path.unlink();self.b.ingest(newer)
  maintain(self.factory)
  with self.factory() as db:self.assertEqual(db.get(HandoffReconciliation,'B').status,'attention')
  self.assertEqual(self.b.snapshot()['papers'][0]['input']['title'],'Updated paper title')
  self.assertEqual(self.task(first).status,'succeeded')
 def test_batch_without_eligible_paper_does_not_switch_b_input(self):
  batch=self.ingest('no-abstract',[record(1,abstract_inverted_index=None)])
  run_one(self.factory)
  self.assertEqual(self.task(batch).status,'failed');self.assertFalse(self.task(batch).retryable)
  self.assertEqual(self.b.read()['batches'],[])
 def test_scheduled_import_keeps_one_retry_owner_and_still_queues_delivery_on_success(self):
  from app.models import CollectionSchedule,CollectionRun,CollectionTask
  with patch('app.formal_batches.upsert_paper',side_effect=ValueError('temporary import failure')):
   batch=self.ingest('scheduled-retry-owner')
  with self.factory() as db:
   plan=CollectionSchedule(id='test-owner',instance_key='fixture',enabled=False,config_json='{}',next_run_at=now())
   db.add(plan);db.flush()
   run=CollectionRun(schedule_id=plan.id,due_at=now(),config_json='{}');db.add(run);db.flush()
   task=CollectionTask(run_id=run.id,venue='CVPR',year=2024,job_id=batch,status='waiting_import')
   db.add(task);db.flush()
   job=db.get(Job,batch);job.next_retry_at=now()-timedelta(seconds=1);db.commit()
   scan(db)
   self.assertEqual(job.status,'partial');self.assertIsNone(job.next_retry_at)
   self.assertEqual(job.retry_attempts,0)
   process_batch(db,job)
   self.assertEqual(job.status,'succeeded');self.assertTrue(self.task(batch).automatic)
