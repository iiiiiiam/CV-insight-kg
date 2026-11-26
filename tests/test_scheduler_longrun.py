"""Accelerated calendar tests: logical days, explicitly separate from real uptime."""
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import select,func
from app.models import database,Job,Paper,CollectionRun
from app.scheduler import sync_schedules,validate_config,tick,recover_scheduler,status
from app.formal_batches import process_batch
from tests.test_formal_batches import record

class LongrunSchedulerTests(unittest.TestCase):
 def test_fourteen_logical_days_with_source_failures_restart_and_unchanged_capture(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);f=database('sqlite:///'+str(root/'test.db'));baseline=root/'baseline/cvpr_2024';baseline.mkdir(parents=True)
   for name in ('baseline.html','baseline.json'):(baseline/name).write_text('fixture baseline')
   config=validate_config({'id':'calendar','time':'09:00','timezone':'Asia/Shanghai','scopes':['CVPR:2024'],'baseline_root':str(root/'baseline'),'output_root':str(root/'captures'),'retry_seconds':1})
   start=datetime(2026,11,1,0,59);sync_schedules(f,[config],start)
   calls=[];failed=set()
   def capture(venue,year,path,**kwargs):
    calls.append(day)
    if day in (3,8) and day not in failed:failed.add(day);raise OSError('Simulated temporary source interruption')
    (path/'formal-input.json').write_text(json.dumps({'format_version':'a-formal-input/1','venue':venue,'year':year,'records':[record(1),record(2)]}))
   try:
    with patch('app.scheduler.freeze_baseline'),patch('app.scheduler.load_baseline'):
     for day in range(14):
      due=start+timedelta(days=day,minutes=1)
      if day in (4,10):recover_scheduler(f);sync_schedules(f,[config],due-timedelta(seconds=1))
      tick(f,due,collector=capture)
      if day in (3,8):tick(f,due+timedelta(seconds=1),collector=capture)
      with f() as db:
       for job in db.scalars(select(Job).where(Job.status=='queued')):process_batch(db,job)
      tick(f,due+timedelta(seconds=2),collector=capture);tick(f,due+timedelta(hours=1),collector=capture)
     with f() as db:
      self.assertEqual(db.scalar(select(func.count()).select_from(CollectionRun)),14)
      self.assertEqual(db.scalar(select(func.count()).select_from(Paper)),2)
      self.assertEqual(db.scalar(select(func.count()).select_from(Job)),1)
     self.assertEqual(len(calls),16)
     self.assertTrue(all(r['status'] in ('succeeded','unchanged') for r in status(f)['runs']))
   finally:f.kw['bind'].dispose()
