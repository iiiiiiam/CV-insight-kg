import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import select,func
from app.models import database,CollectionRun,CollectionTask,CollectionSchedule,Job,JobRecord,Paper
from app.scheduler import validate_config,sync_schedules,enqueue_due,tick,status,recover_scheduler
from app.formal_batches import process_batch,digest,queue_batch,withdraw_batch
from app.worker_lock import worker_lock
from tests.test_formal_batches import record


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.factory=database('sqlite:///'+str(self.root/'schedule.db'))
        self.config=validate_config({'id':'daily','time':'09:00','timezone':'Asia/Shanghai','scopes':['CVPR:2024'],'baseline_root':str(self.root/'baseline'),'output_root':str(self.root/'captures'),'retry_seconds':5,'max_attempts':3})
        baseline=self.root/'baseline/cvpr_2024';baseline.mkdir(parents=True)
        (baseline/'baseline.html').write_text('frozen baseline');(baseline/'baseline.json').write_text('{}')
        self.patches=[patch('app.scheduler.freeze_baseline'),patch('app.scheduler.load_baseline')]
        for p in self.patches:p.start()
        self.start=datetime(2026,11,13,0,59)
        sync_schedules(self.factory,[self.config],self.start)
        self.records=[record(1),record(2)];self.calls=0
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.factory.kw['bind'].dispose();self.tmp.cleanup()
    def collect(self,venue,year,directory,**kwargs):
        self.assertTrue(kwargs['require_all_sources']);self.calls+=1
        (directory/'formal-input.json').write_text(json.dumps({'format_version':'a-formal-input/1','venue':venue,'year':year,'records':self.records}))
    def finish_import(self):
        with self.factory() as db:
            for job in db.scalars(select(Job).where(Job.status=='queued')):process_batch(db,job)
    def test_daily_trigger_import_and_unchanged_next_day(self):
        tick(self.factory,self.start,collector=self.collect);self.assertEqual(self.calls,0)
        due=self.start+timedelta(minutes=1)
        def observe_collection(*args, **kwargs):
            active = status(self.factory)['runs'][0]
            self.assertEqual(active['status'], 'running')
            self.assertEqual(active['tasks'][0]['status'], 'collecting')
            return self.collect(*args, **kwargs)
        tick(self.factory,due,collector=observe_collection)
        self.assertEqual(status(self.factory)['runs'][0]['status'],'waiting_import')
        self.finish_import();tick(self.factory,due+timedelta(seconds=1),collector=self.collect)
        self.assertEqual(status(self.factory)['runs'][0]['status'],'succeeded')
        tick(self.factory,due+timedelta(hours=2),collector=self.collect)
        self.assertEqual(self.calls,1)
        tick(self.factory,due+timedelta(days=1),collector=self.collect)
        state=status(self.factory);self.assertEqual(state['runs'][0]['status'],'unchanged')
        self.assertEqual(state['runs'][0]['tasks'][0]['unchanged_records'],2)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),2)
    def test_restart_catches_only_latest_slot_and_uses_saved_next_time(self):
        late=self.start+timedelta(days=4,hours=3)
        sync_schedules(self.factory,[self.config],late)
        self.assertEqual(len(enqueue_due(self.factory,late)),1)
        self.assertEqual(enqueue_due(self.factory,late),[])
        result=status(self.factory)
        self.assertEqual(result['runs'][0]['trigger'],'catch_up')
        self.assertEqual(result['runs'][0]['scheduled_for_utc'],'2026-11-17T01:00:00Z')
        self.assertEqual(result['schedules'][0]['next_run_local'],'2026-11-18T09:00:00+08:00')
    def test_failed_collection_retries_with_backoff_and_stops(self):
        due=self.start+timedelta(minutes=1)
        def broken(*a,**kw):raise OSError('temporary provider failure')
        tick(self.factory,due,collector=broken)
        tick(self.factory,due+timedelta(seconds=4),collector=broken)
        self.assertEqual(status(self.factory)['runs'][0]['tasks'][0]['attempts'],1)
        tick(self.factory,due+timedelta(seconds=5),collector=broken)
        tick(self.factory,due+timedelta(seconds=10),collector=broken)
        tick(self.factory,due+timedelta(seconds=20),collector=broken)
        task=status(self.factory)['runs'][0]['tasks'][0]
        self.assertEqual((task['status'],task['attempts']),('failed',3))
        with self.factory() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Job)),0)
    def test_new_and_changed_sources_create_only_delta_and_keep_ids(self):
        due=self.start+timedelta(minutes=1)
        tick(self.factory,due,collector=self.collect);self.finish_import();tick(self.factory,due,collector=self.collect)
        with self.factory() as db:old_ids=list(db.scalars(select(Paper.id).order_by(Paper.id)))
        self.records=[record(1),record(2,cited_by_count=7),record(3)]
        tick(self.factory,due+timedelta(days=1),collector=self.collect);self.finish_import();tick(self.factory,due+timedelta(days=1),collector=self.collect)
        task=status(self.factory)['runs'][0]['tasks'][0]
        self.assertEqual((task['collected_records'],task['unchanged_records']),(3,1))
        with self.factory() as db:
            self.assertEqual(list(db.scalars(select(Paper.id).order_by(Paper.id)))[:2],old_ids)
            self.assertEqual(db.scalar(select(func.count()).select_from(JobRecord).where(JobRecord.job_id==task['job_id'])),2)
    def test_recover_batch_created_before_task_saved_and_never_reactivate_withdrawn(self):
        from app.scheduler import task_key
        due=self.start+timedelta(minutes=1);enqueue_due(self.factory,due)
        with self.factory() as db:
            task=db.scalar(select(CollectionTask));run=db.get(CollectionRun,task.run_id)
            job,_=queue_batch(db,task_key(json.loads(run.config_json),run,task),'CVPR',2024,self.records)
            task.status='collecting';task.attempts=1;db.commit();identifier=job.id
        recover_scheduler(self.factory);tick(self.factory,due+timedelta(seconds=1),collector=self.collect)
        self.assertEqual(self.calls,0);self.finish_import()
        with self.factory() as db:withdraw_batch(db,identifier,'cancel scheduled batch')
        tick(self.factory,due+timedelta(seconds=2),collector=self.collect)
        self.assertEqual(status(self.factory)['runs'][0]['tasks'][0]['status'],'cancelled')
        with self.factory() as db:self.assertEqual(db.scalar(select(func.count()).select_from(Job)),1)
    def test_partial_import_retries_same_job_preserving_checkpoint(self):
        from app.formal_batches import upsert_paper
        due=self.start+timedelta(minutes=1);tick(self.factory,due,collector=self.collect)
        def fail(db,row,*a,**kw):
            if row['source_id'].endswith('W2'):raise OSError('temporary import error')
            return upsert_paper(db,row,*a,**kw)
        with patch('app.formal_batches.upsert_paper',side_effect=fail):self.finish_import()
        tick(self.factory,due+timedelta(seconds=1),collector=self.collect)
        self.assertEqual(status(self.factory)['runs'][0]['status'],'retrying')
        tick(self.factory,due+timedelta(seconds=6),collector=self.collect);self.finish_import();tick(self.factory,due+timedelta(seconds=7),collector=self.collect)
        self.assertEqual(status(self.factory)['runs'][0]['status'],'succeeded')
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Job)),1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),2)
    def test_disabled_schedule_does_not_collect_and_configuration_validates(self):
        sync_schedules(self.factory,[],self.start)
        tick(self.factory,self.start+timedelta(days=1),collector=self.collect);self.assertEqual(self.calls,0)
        for change in ({'scopes':[{}]},{'time':'25:00'},{'scopes':['ICCV:2024']},{'max_attempts':0}):
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):validate_config({**self.config,**change})
    def test_scheduler_and_worker_locks_are_distinct_but_two_timers_rejected(self):
        with worker_lock(self.factory),worker_lock(self.factory,role='scheduler'):
            with self.assertRaises((OSError,RuntimeError)):
                with worker_lock(self.factory,role='scheduler'):pass

    def test_withdrawn_update_can_be_collected_again_against_effective_snapshot(self):
        from app.scheduler import changed_records
        with self.factory() as db:
            first,_=queue_batch(db,'original','CVPR',2024,[record(10)])
            process_batch(db,first)
            second,_=queue_batch(db,'update','CVPR',2024,[record(10,cited_by_count=9)])
            process_batch(db,second)
            withdraw_batch(db,second.id,'rollback refreshed metadata')
            self.assertEqual(changed_records(db,[record(10)]),[])
            self.assertEqual(changed_records(db,[record(10,cited_by_count=9)]),[record(10,cited_by_count=9)])
    def test_source_present_only_in_withdrawn_version_is_a_new_delta(self):
        from app.scheduler import changed_records
        dblp={'source':'dblp','row':{'source_id':'conf/cvpr/Test2024','dblp_key':'conf/cvpr/Test2024','venue':'CVPR','year':2024,'title':'Research Paper 10','authors':['Test Author'],'doi':'10.1234/10','source_url':'https://dblp.org/rec/conf/cvpr/Test2024','raw':{'title':'Research Paper 10'}}}
        with self.factory() as db:
            first,_=queue_batch(db,'original','CVPR',2024,[record(10)]);process_batch(db,first)
            second,_=queue_batch(db,'source-added','CVPR',2024,[dblp]);process_batch(db,second)
            withdraw_batch(db,second.id,'remove extra source')
            self.assertEqual(changed_records(db,[dblp]),[dblp])
    def test_disabled_source_pauses_without_consuming_collection_attempts(self):
        from app.models import Source
        due=self.start+timedelta(minutes=1)
        with self.factory() as db:db.add(Source(name='openalex',enabled=False));db.commit()
        tick(self.factory,due,collector=self.collect)
        state=status(self.factory)['runs'][0]['tasks'][0]
        self.assertEqual((state['status'],state['attempts'],self.calls),('paused',0,0))
        with self.factory() as db:db.scalar(select(Source)).enabled=True;db.commit()
        tick(self.factory,due+timedelta(seconds=5),collector=self.collect)
        self.assertEqual(self.calls,1)

    def test_source_parameters_are_frozen_across_capture_retry(self):
        from app.models import Source
        seen=[];due=self.start+timedelta(minutes=1)
        with self.factory() as db:db.add(Source(name='openalex',page_size=70,max_retries=2));db.commit()
        def first(*args,**kwargs):seen.append(kwargs['source_options']);raise OSError('interrupted capture')
        tick(self.factory,due,collector=first)
        with self.factory() as db:db.scalar(select(Source)).page_size=20;db.commit()
        def retry(*args,**kwargs):seen.append(kwargs['source_options']);return self.collect(*args,**kwargs)
        tick(self.factory,due+timedelta(seconds=5),collector=retry)
        self.assertEqual(seen,[{'openalex':{'page_size':70,'max_retries':2}}]*2)
