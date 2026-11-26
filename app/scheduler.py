"""Persistent daily collection: timezone-aware slots, delta ingestion, bounded retries and restart recovery."""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta,timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from sqlalchemy import select,update,func
from .models import CollectionSchedule,CollectionRun,CollectionTask,CollectionRuntime,Job,JobRecord,PaperSource,StablePaper,BatchLedger,now
from .formal_batches import canonical,digest,queue_batch
from .formal_collection import collect_scope,freeze_baseline,load_baseline
from .paths import project_path
from .pipeline import safe_error

LOG=logging.getLogger('a.scheduler')
TERMINAL={'succeeded','unchanged','failed','partial','cancelled'}


def utc(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def validate_config(config):
    value=dict(config)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',value.get('id','')):raise ValueError('Invalid schedule ID')
    if type(value.get('enabled',True))is not bool or type(value.get('with_annotations',False))is not bool:raise ValueError('Schedule flags must be booleans')
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value.get('time','')):raise ValueError('Use daily time HH:MM')
    try:ZoneInfo(value.get('timezone','Asia/Shanghai'))
    except (ZoneInfoNotFoundError,TypeError) as exc:raise ValueError('Invalid timezone') from exc
    scopes=value.get('scopes')
    if not isinstance(scopes,list) or not scopes or not all(isinstance(s,str) for s in scopes) or len(scopes)!=len(set(scopes)):raise ValueError('Provide unique conference scopes')
    for scope in scopes:
        if not isinstance(scope,str) or not re.fullmatch(r'(CVPR|ICCV):[0-9]{4}',scope):raise ValueError('Invalid conference scope')
        venue,year=scope.split(':');year=int(year)
        if not 1980<=year<=now().year or (venue=='ICCV' and year%2==0):raise ValueError('Invalid completed conference edition')
    for name,default,lower,upper in [('max_attempts',3,1,8),('retry_seconds',300,1,86400)]:
        number=value.get(name,default)
        if type(number)is not int or not lower<=number<=upper:raise ValueError('Invalid '+name)
        value[name]=number
    for name,default in [('baseline_root','data/week3/collection'),('output_root','data/scheduled')]:
        if not isinstance(value.get(name,default),str) or not value.get(name,default):raise ValueError('Invalid '+name)
        value[name]=value.get(name,default)
    value.setdefault('enabled',True);value.setdefault('timezone','Asia/Shanghai');value.setdefault('with_annotations',False)
    return value


def default_config():
    return validate_config(dict(id='daily-papers',enabled=False,time='09:00',timezone='Asia/Shanghai',
        scopes=['CVPR:2023','ICCV:2021'],with_annotations=True,
        baseline_root=os.getenv('A_COLLECTION_ROOT','data/week3/collection'),
        output_root=os.getenv('A_SCHEDULE_ROOT','data/scheduled')))


def ensure_default(factory):
    from sqlalchemy.exc import IntegrityError
    with factory() as db:
        if db.get(CollectionSchedule,'daily-papers') is None:
            config=default_config()
            db.add(CollectionSchedule(id=config['id'],instance_key=uuid.uuid4().hex,enabled=False,
                config_json=canonical(config),next_run_at=slot(now(),config,next_slot=True)))
            try:db.commit()
            except IntegrityError:db.rollback()


def attempt_limit(task,config):
    return config['max_attempts']*(1+(task.retry_round or 0))


def load_config(path):
    values=json.loads(project_path(path).read_text(encoding='utf-8'))['schedules']
    if not isinstance(values,list):raise ValueError('schedules must be a list')
    configs=[validate_config(v) for v in values]
    if len({c['id'] for c in configs})!=len(configs):raise ValueError('Schedule IDs must be unique')
    return configs


def slot(moment,config,*,next_slot):
    aware=utc(moment).replace(tzinfo=timezone.utc).astimezone(ZoneInfo(config['timezone']))
    hour,minute=map(int,config['time'].split(':'))
    local=aware.replace(hour=hour,minute=minute,second=0,microsecond=0,fold=0)
    candidate=utc(local)
    if next_slot and candidate<=utc(moment):candidate=utc(local+timedelta(days=1))
    if not next_slot and candidate>utc(moment):candidate=utc(local-timedelta(days=1))
    return candidate


def sync_schedules(factory,configs,moment=None):
    moment=utc(moment or now());identifiers=[c['id'] for c in configs]
    with factory() as db:
        for saved in db.scalars(select(CollectionSchedule)):
            if saved.id not in identifiers:saved.enabled=False
        for config in configs:
            config=validate_config(config);saved=db.get(CollectionSchedule,config['id'])
            if saved is None:
                saved=CollectionSchedule(id=config['id'],instance_key=uuid.uuid4().hex,enabled=config['enabled'],config_json=canonical(config),next_run_at=slot(moment,config,next_slot=True));db.add(saved)
            else:
                old=json.loads(saved.config_json)
                if old.get('time')!=config['time'] or old.get('timezone')!=config['timezone'] or (config['enabled'] and not saved.enabled):saved.next_run_at=slot(moment,config,next_slot=True)
                saved.config_json=canonical(config);saved.enabled=config['enabled'];saved.updated_at=moment
        db.commit()


def new_run(db,schedule,due,trigger):
    existing=db.scalar(select(CollectionRun).where(CollectionRun.schedule_id==schedule.id,CollectionRun.due_at==due))
    if existing:return existing
    config=json.loads(schedule.config_json);config['instance_key']=schedule.instance_key
    run=CollectionRun(schedule_id=schedule.id,due_at=due,trigger=trigger,config_json=canonical(config));db.add(run);db.flush()
    for scope in config['scopes']:
        venue,year=scope.split(':');db.add(CollectionTask(run_id=run.id,venue=venue,year=int(year)))
    return run


def enqueue_due(factory,moment=None,*,run_now=False):
    moment=utc(moment or now());created=[]
    with factory() as db:
        for schedule in db.scalars(select(CollectionSchedule).where(CollectionSchedule.enabled.is_(True)).order_by(CollectionSchedule.id)):
            config=json.loads(schedule.config_json)
            if run_now:
                run=new_run(db,schedule,moment.replace(microsecond=0),'manual');created.append(run.id)
            if schedule.next_run_at<=moment:
                old=schedule.next_run_at
                claimed=db.execute(update(CollectionSchedule).where(CollectionSchedule.id==schedule.id,CollectionSchedule.next_run_at==old).values(next_run_at=slot(moment,config,next_slot=True))).rowcount
                if claimed:
                    due=slot(moment,config,next_slot=False)
                    run=new_run(db,schedule,due,'catch_up' if due>old else 'scheduled');created.append(run.id)
        db.commit()
    return sorted(set(created))


def recover_scheduler(factory):
    with factory() as db:
        for task in db.scalars(select(CollectionTask).where(CollectionTask.status=='collecting')):
            task.status='retry_wait';task.next_attempt_at=now();task.error='Scheduler restarted; resuming the saved capture and batch key'
        db.commit()


def changed_records(db,records):
    existing={};saved_keys={}
    for source in {r['source'] for r in records}:
        ids=[r['row']['source_id'] for r in records if r['source']==source]
        for offset in range(0,len(ids),500):
            rows=db.execute(select(PaperSource,StablePaper.active).outerjoin(StablePaper,StablePaper.paper_id==PaperSource.paper_id).where(PaperSource.source==source,PaperSource.source_id.in_(ids[offset:offset+500]))).all()
            for saved,active in rows:
                key=(saved.source,saved.source_id)
                existing[key]=(json.loads(saved.raw_json),active)
                saved_keys.setdefault(saved.paper_id,[]).append(key)
    # Compare against the currently effective frozen version. PaperSource also
    # retains the last observed raw data, which can belong to a withdrawn batch.
    from sqlalchemy import func
    from .models import BatchPaperVersion
    paper_ids=set()
    for source in {r['source'] for r in records}:
        ids=[r['row']['source_id'] for r in records if r['source']==source]
        for offset in range(0,len(ids),500):
            paper_ids.update(db.scalars(select(PaperSource.paper_id).join(StablePaper,StablePaper.paper_id==PaperSource.paper_id).where(PaperSource.source==source,PaperSource.source_id.in_(ids[offset:offset+500]))))
    identifiers=list(paper_ids)
    for offset in range(0,len(identifiers),500):
        latest=(select(BatchPaperVersion.paper_id.label('paper_id'),func.max(BatchPaperVersion.job_id).label('job_id'))
            .join(BatchLedger,BatchLedger.job_id==BatchPaperVersion.job_id)
            .where(BatchLedger.withdrawn.is_(False),BatchPaperVersion.paper_id.in_(identifiers[offset:offset+500]))
            .group_by(BatchPaperVersion.paper_id).subquery())
        for frozen in db.scalars(select(BatchPaperVersion).join(latest,(latest.c.paper_id==BatchPaperVersion.paper_id)&(latest.c.job_id==BatchPaperVersion.job_id))):
            for key in saved_keys.get(frozen.paper_id,[]):existing.pop(key,None)
            for source in json.loads(frozen.content_json)['sources']:
                existing[(source['source'],source['source_id'])]=(source['raw'],True)
    changed=[]
    for record in records:
        previous=existing.get((record['source'],record['row']['source_id']))
        if previous is None or previous[1] is False or previous[0]!=record['row'].get('raw',record['row']):changed.append(record)
    return changed


def task_key(config,run,task):
    return f"auto:{config['instance_key']}:{run.schedule_id}:{run.due_at.strftime('%Y%m%dT%H%M%S')}:{task.venue}:{task.year}"


def fail_task(factory,task_id,error,moment,config,owner_check=None):
    if owner_check:owner_check()
    with factory() as db:
        task=db.get(CollectionTask,task_id);task.error=safe_error(error)
        task.status='retry_wait' if task.attempts<attempt_limit(task,config) else 'failed'
        task.next_attempt_at=moment+timedelta(seconds=config['retry_seconds']) if task.status=='retry_wait' else None
        # A corrupt/changing capture is preserved for diagnosis; retries start a clean capture.
        if isinstance(error,json.JSONDecodeError) or any(word in str(error).lower() for word in ('checksum','checkpoint','count changed','scope mismatch','jsondecodeerror')):task.generation+=1
        task.updated_at=moment;db.commit()
    LOG.warning('Collection task %s: %s',task_id,safe_error(error))


def process_task(factory,task_id,moment,collector,owner_check=None):
    with factory() as db:
        task=db.get(CollectionTask,task_id);run=db.get(CollectionRun,task.run_id);config=json.loads(run.config_json)
        if task.status in TERMINAL:return
        ledger=db.scalar(select(BatchLedger).where(BatchLedger.batch_key==task_key(config,run,task)))
        if ledger is not None:task.job_id=ledger.job_id
        if task.job_id:
            job=db.get(Job,task.job_id)
            if ledger is None:ledger=db.get(BatchLedger,task.job_id)
            if ledger is None:raise ValueError('Scheduled import has no batch ledger')
            if ledger.withdrawn:task.status='cancelled';task.error='Batch withdrawn; this scheduled run will not reactivate it';db.commit();return
            if job.status in ('queued','running'):task.status='waiting_import';db.commit();return
            if job.status=='succeeded':task.status='succeeded';task.error=None;db.commit();return
            if task.status!='retry_wait':
                task.status='retry_wait' if task.attempts<attempt_limit(task,config) else 'failed';task.error=job.error or 'Import failed';task.next_attempt_at=moment+timedelta(seconds=config['retry_seconds']);db.commit();return
            if task.next_attempt_at and task.next_attempt_at>moment:return
            if task.attempts>=attempt_limit(task,config):task.status='failed';db.commit();return
            from .formal_batches import lock_scope
            from .pipeline import saved_progress
            lock_scope(db,job.venue,job.year)
            if db.scalar(select(Job.id).where(Job.venue==job.venue,Job.year==job.year,Job.status.in_(('queued','running'))).limit(1)):return
            counts=saved_progress(db,job);job.succeeded=counts['succeeded'];job.failed=counts['failed'];job.skipped=counts['skipped'];job.attempted=job.succeeded+job.failed+job.skipped
            job.status='queued';job.stage='queued';job.active_key=f'{job.venue}:{job.year}';job.error=None;job.finished_at=None
            task.attempts+=1;task.status='waiting_import';task.next_attempt_at=None;db.commit();return
        if task.next_attempt_at and task.next_attempt_at>moment:return
        if task.attempts>=attempt_limit(task,config):task.status='failed';db.commit();return
        from .models import Source
        disabled=list(db.scalars(select(Source.name).where(Source.name.in_(('dblp','openalex')),Source.enabled.is_(False))))
        if disabled:
            task.status='paused';task.error='来源已停用：'+', '.join(disabled);task.next_attempt_at=moment+timedelta(seconds=config['retry_seconds']);db.commit();return
        task.attempts+=1;task.status='collecting';task.updated_at=moment;task.error=None
        run.status = 'running'
        capture=project_path(config['output_root'])/config['instance_key']/f'run-{run.id:06d}'/f'{task.venue.lower()}_{task.year}'/f'capture-{task.generation}'
        task.capture_dir=str(capture);venue,year=task.venue,task.year;key=task_key(config,run,task);db.commit()
    try:
        baseline_dir=project_path(config['baseline_root'])/f'{venue.lower()}_{year}'
        freeze_baseline(venue,year,baseline_dir);load_baseline(baseline_dir/'baseline.json',venue,year)
        capture.mkdir(parents=True,exist_ok=True)
        for name in ('baseline.html','baseline.json'):
            target=capture/name
            if not target.exists():shutil.copy2(baseline_dir/name,target)
        options_file=capture/'source-options.json'
        if options_file.exists():
            try:
                options=json.loads(options_file.read_text());checksum=options.pop('sha256')
                if digest(options)!=checksum:raise ValueError('Source options checksum mismatch')
            except (json.JSONDecodeError,KeyError,TypeError,AttributeError) as exc:
                raise ValueError('Source options checksum/schema mismatch') from exc
        else:
            with factory() as db:
                from .models import Source
                options={s.name:{'page_size':min(100,s.page_size) if s.name=='openalex' else s.page_size,'max_retries':s.max_retries} for s in db.scalars(select(Source).where(Source.name.in_(('dblp','openalex'))))}
            from .formal_collection import write_json
            write_json(options_file,options|{'sha256':digest(options)})
        collector(venue,year,capture,with_annotations=config['with_annotations'],require_all_sources=True,source_options=options)
        if owner_check:owner_check()
        payload=json.loads((capture/'formal-input.json').read_text(encoding='utf-8'))
        if payload.get('format_version')!='a-formal-input/1' or (payload.get('venue'),payload.get('year'))!=(venue,year):raise ValueError('Collected input scope mismatch')
        delta_file=capture/'scheduled-delta.json'
        with factory() as db:
            task=db.get(CollectionTask,task_id)
            if delta_file.exists():
                delta=json.loads(delta_file.read_text());checksum=delta.pop('sha256')
                if digest(delta)!=checksum:raise ValueError('Scheduled delta checksum mismatch')
                records=delta['records']
            else:
                records=changed_records(db,payload['records']);delta={'venue':venue,'year':year,'records':records};delta['sha256']=digest(delta)
                from .formal_collection import write_json
                write_json(delta_file,delta)
            task.collected_records=len(payload['records']);task.unchanged_records=len(payload['records'])-len(records)
            if not records:task.status='unchanged';task.error=None;db.commit();return
            job,_=queue_batch(db,key,venue,year,records)
            task.job_id=job.id;task.status='waiting_import';task.next_attempt_at=None;task.error=None;db.commit()
    except Exception as exc:fail_task(factory,task_id,exc,moment,config,owner_check)


def refresh_runs(factory,moment):
    with factory() as db:
        for run in db.scalars(select(CollectionRun).where(CollectionRun.status.not_in(TERMINAL))):
            statuses=list(db.scalars(select(CollectionTask.status).where(CollectionTask.run_id==run.id)))
            if all(s in TERMINAL for s in statuses):
                successful=sum(s in ('succeeded','unchanged') for s in statuses)
                run.status='unchanged' if all(s=='unchanged' for s in statuses) else 'succeeded' if successful==len(statuses) else 'partial' if successful else 'failed';run.finished_at=moment
            else:run.status='retrying' if 'retry_wait' in statuses else 'waiting_import' if 'waiting_import' in statuses else 'running'
        db.commit()


def tick(factory,moment=None,*,collector=collect_scope,owner_check=None,run_now=False):
    moment=utc(moment or now());enqueue_due(factory,moment,run_now=run_now)
    with factory() as db:
        # Disabling a plan stops future triggers; already-created runs finish normally.
        ids=list(db.scalars(select(CollectionTask.id).join(CollectionRun,CollectionRun.id==CollectionTask.run_id).where(CollectionRun.status.not_in(TERMINAL),CollectionTask.status.not_in(TERMINAL)).order_by(CollectionTask.id)))
    for task_id in ids:
        if owner_check:owner_check()
        process_task(factory,task_id,moment,collector,owner_check)
    refresh_runs(factory,moment)


def status(factory,limit=20):
    with factory() as db:
        schedules=[]
        for s in db.scalars(select(CollectionSchedule).order_by(CollectionSchedule.id)):
            config=json.loads(s.config_json)
            schedules.append({k:config[k] for k in ('id','enabled','time','timezone','scopes','with_annotations','max_attempts','retry_seconds')}|
                {'enabled':s.enabled,'revision':digest(config),'next_run_utc':s.next_run_at.isoformat()+'Z',
                 'next_run_local':s.next_run_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(config['timezone'])).isoformat()})
        runs=[]
        for run in db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(limit)):
            tasks=[]
            for t in db.scalars(select(CollectionTask).where(CollectionTask.run_id==run.id).order_by(CollectionTask.id)):
                job=db.get(Job,t.job_id) if t.job_id else None
                total=db.scalar(select(func.count()).select_from(JobRecord).where(JobRecord.job_id==t.job_id)) if job else 0
                from .batch_labels import batch_labels
                tasks.append({'venue':t.venue,'year':t.year,'status':t.status,'attempts':t.attempts,'retry_round':t.retry_round,
                    'job_id':t.job_id,'display_code':batch_labels(job)['display_code'] if job else None,
                    'batch_state':'withdrawn' if job and (ledger:=db.get(BatchLedger,job.id)) and ledger.withdrawn else 'active' if job else None,
                    'progress':{'total':total,'finished':job.attempted if job else 0,'percent':min(100,round(job.attempted/total*100)) if total else 0},
                    'collected_records':t.collected_records,'unchanged_records':t.unchanged_records,'error':t.error,
                    'next_attempt_utc':t.next_attempt_at.isoformat()+'Z' if t.next_attempt_at else None})
            runs.append({'run_id':run.id,'schedule_id':run.schedule_id,'scheduled_for_utc':run.due_at.isoformat()+'Z','trigger':run.trigger,'status':run.status,'tasks':tasks})
        runtime=db.get(CollectionRuntime,'scheduler')
        connected=bool(runtime and runtime.state!='stopped' and (now()-runtime.last_seen_at).total_seconds()<30)
        return {'schedules':schedules,'runs':runs,'runtime':{'connected':connected,
            'state':runtime.state if connected else 'stopped','error':runtime.error if runtime else None,
            'last_seen_utc':runtime.last_seen_at.isoformat()+'Z' if runtime else None}}


def heartbeat(factory,state='running',error=None):
    with factory() as db:
        saved=db.get(CollectionRuntime,'scheduler')
        if saved is None:saved=CollectionRuntime(id='scheduler');db.add(saved)
        saved.last_seen_at=now();saved.state=state;saved.error=error;db.commit()


def main():
    parser=argparse.ArgumentParser(description='Persistent daily paper collection and automatic delta import')
    parser.add_argument('--config',type=Path,help='Explicitly load plan configuration from a file');parser.add_argument('--once',action='store_true');parser.add_argument('--run-now',action='store_true');parser.add_argument('--status',action='store_true');parser.add_argument('--poll-seconds',type=int,default=5)
    args=parser.parse_args()
    if args.poll_seconds<1:parser.error('poll interval must be positive')
    from .db import SessionLocal
    from .worker_lock import worker_lock
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.status:print(json.dumps(status(SessionLocal),ensure_ascii=False,indent=2));return
    with worker_lock(SessionLocal,role='scheduler') as check_owner:
        from .db import seed_sources
        seed_sources()
        if args.config:sync_schedules(SessionLocal,load_config(args.config))
        else:ensure_default(SessionLocal)
        recover_scheduler(SessionLocal)
        import threading
        stop=threading.Event()
        def keep_alive():
            while not stop.wait(5):
                try:heartbeat(SessionLocal)
                except Exception:LOG.exception('Scheduler heartbeat failed')
        heartbeat(SessionLocal)
        watcher=threading.Thread(target=keep_alive,daemon=True);watcher.start()
        LOG.info('Automatic collection started: %s',json.dumps(status(SessionLocal)['schedules'],ensure_ascii=False))
        first=True
        try:
            while True:
                check_owner()
                try:tick(SessionLocal,owner_check=check_owner,run_now=args.run_now and first)
                except Exception as exc:
                    heartbeat(SessionLocal,'error',safe_error(exc));LOG.error('Scheduler cycle failed: %s',safe_error(exc))
                first=False
                if args.once:print(json.dumps(status(SessionLocal),ensure_ascii=False,indent=2));return
                time.sleep(args.poll_seconds)
        finally:
            stop.set();watcher.join(timeout=10);heartbeat(SessionLocal,'stopped')

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:pass
