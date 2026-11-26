"""Small live OpenAlex imports with durable checkpoints and the formal batch ledger."""
import json
import os
import re
import time
from uuid import uuid4

import requests
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from .models import OnlineCollection,Job,JobRecord,JobEvent,Source,BatchLedger,StablePaper,WorkflowTask,now
from .formal_batches import canonical,digest,lock_scope,prior_paper,process_batch
from .ingest import openalex_work_row
from .paper_quality import is_front_matter
from .batch_labels import batch_labels
from scripts.fetch_openalex_batch import SOURCES,FIELDS,ANNOTATION_FIELDS


class OnlineInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_key:str=Field(default_factory=lambda:uuid4().hex,min_length=1,max_length=180)
    venue:str='CVPR'
    year:int=2025
    count:int=Field(default=20,ge=1,le=50)
    keyword:str=Field(default='',max_length=200)


def queue_online(db,body):
    value=body.model_dump();value['venue']=value['venue'].upper();value['keyword']=value['keyword'].strip()
    key=digest(value['request_key']);checksum=digest(value)
    old=db.scalar(select(OnlineCollection).where(OnlineCollection.request_key==key))
    if old:
        if old.request_sha256!=checksum:raise ValueError('同一请求编号的采集条件已变化，请重新提交')
        return db.get(Job,old.job_id),True
    venue,year=value['venue'],value['year']
    if venue not in SOURCES or not 1980<=year<=now().year or venue=='ICCV' and year%2==0:
        raise ValueError('请选择支持的会议和年份')
    source=db.scalar(select(Source).where(Source.name=='openalex'))
    if not source or not source.enabled:raise ValueError('OpenAlex 来源已停用，请先在来源配置中启用')
    lock_scope(db,venue,year)
    if db.scalar(select(Job.id).where(Job.venue==venue,Job.year==year,Job.status.in_(('queued','running'))).limit(1)):
        raise ValueError('该会议年度已有任务正在处理，请等待完成')
    job=Job(venue=venue,year=year,source='openalex',kind='online',import_mode='manual',
        active_key=f'{venue}:{year}',status='queued',stage='queued')
    db.add(job);db.flush();job.dataset_id=f'online:openalex:{job.id}'
    db.add(OnlineCollection(job_id=job.id,request_key=key,request_sha256=checksum,
        requested_count=value['count'],keyword=value['keyword']))
    db.commit();return job,False


def already_imported(db,row):
    paper=prior_paper(db,row,'openalex')
    if paper is None:return False
    stable=db.get(StablePaper,paper.id)
    return stable is None or stable.active


def process_online(db,job,http=None):
    saved=db.get(OnlineCollection,job.id)
    if saved is None:raise ValueError('在线采集任务不存在')
    if db.get(BatchLedger,job.id):
        process_batch(db,job);return
    configured=db.scalar(select(Source).where(Source.name=='openalex'))
    if not configured or not configured.enabled:raise ValueError('OpenAlex 来源已停用，请启用后重试')
    job.status,job.stage,job.error='running','collect',None
    job.started_at=job.started_at or now();db.commit()
    works=json.loads(saved.records_json)
    owned=http is None;http=http or requests.Session()
    try:
        while len(works)<saved.requested_count and not saved.exhausted and saved.next_page<=5:
            page_size=min(100,configured.page_size)
            params={'filter':f'primary_location.source.id:{SOURCES[job.venue]},publication_year:{job.year},has_abstract:true',
                'per_page':page_size,'page':saved.next_page,'sort':'cited_by_count:desc','select':FIELDS+','+ANNOTATION_FIELDS}
            if saved.keyword:params['search']=saved.keyword
            if os.getenv('OPENALEX_API_KEY'):params['api_key']=os.environ['OPENALEX_API_KEY']
            for attempt in range(configured.max_retries):
                try:
                    response=http.get('https://api.openalex.org/works',params=params,timeout=(5,25))
                    response.raise_for_status();payload=response.json()
                    if not isinstance(payload.get('results'),list):raise ValueError('在线来源返回格式有变化，请稍后重试')
                    break
                except requests.RequestException:
                    if attempt+1>=configured.max_retries:
                        raise ValueError('OpenAlex 暂不可用，请稍后重试本次采集任务') from None
                    time.sleep(min(attempt+1,3))
            identifiers={w['id'] for w in works}
            page_seen=set()
            for work in payload['results']:
                if len(works)>=saved.requested_count:break
                saved.scanned_count+=1
                identifier=work.get('id') if isinstance(work,dict) else None
                if identifier in identifiers or identifier in page_seen:continue
                page_seen.add(identifier)
                try:
                    if not isinstance(identifier,str) or not re.fullmatch(r'https://openalex.org/W\d+',identifier):raise ValueError()
                    if work.get('publication_year')!=job.year or ((work.get('primary_location') or {}).get('source') or {}).get('id')!='https://openalex.org/'+SOURCES[job.venue]:
                        raise ValueError()
                    row=openalex_work_row(work,job.venue,job.year)
                    if is_front_matter(row) or not row.get('abstract') or not row.get('authors'):raise ValueError()
                except (ValueError,KeyError,TypeError,AttributeError):
                    saved.skipped_count+=1;continue
                if already_imported(db,row):saved.existing_count+=1;continue
                works.append(work);identifiers.add(identifier)
            saved.next_page+=1
            saved.exhausted=len(payload['results'])<page_size
            saved.records_json=canonical(works);job.updated_at=now();db.commit()
    finally:
        if owned:http.close()
    if not works:
        job.status,job.stage,job.active_key='succeeded','unchanged',None
        job.finished_at=now();job.next_retry_at=None
        db.add(JobEvent(job_id=job.id,stage='done',level='info',message='本次查询没有符合条件的未入库论文'))
        db.commit();return
    rows=[{'source':'openalex','row':openalex_work_row(work,job.venue,job.year)} for work in works]
    db.add(BatchLedger(job_id=job.id,batch_key=job.dataset_id,input_sha256=digest({'venue':job.venue,'year':job.year,'records':rows})))
    db.add_all(JobRecord(job_id=job.id,source='openalex',source_id=r['row']['source_id'],payload_json=canonical(r['row'])) for r in rows)
    job.kind,job.stage='formal','upsert';db.commit()
    process_batch(db,job)


def online_view(db,identifier):
    saved=db.get(OnlineCollection,identifier);job=db.get(Job,identifier)
    if saved is None or job is None:raise LookupError('未找到在线采集记录')
    selected=len(json.loads(saved.records_json))
    task=db.scalar(select(WorkflowTask).options(defer(WorkflowTask.payload_json)).where(
        WorkflowTask.batch_id==identifier,WorkflowTask.kind=='handoff').order_by(WorkflowTask.created_at.desc()).limit(1))
    from .workflow_tasks import view
    from .formal_batches import batch_manifest
    manifest=batch_manifest(db,identifier) if db.get(BatchLedger,identifier) else None
    progress=100 if job.status=='succeeded' else (min(95,70+int(25*job.attempted/max(selected,1)))
        if job.kind=='formal' else min(70,int(70*selected/saved.requested_count)))
    return dict(id=identifier,venue=job.venue,year=job.year,status=job.status,stage=job.stage,
        requested_count=saved.requested_count,selected_count=selected,scanned_count=saved.scanned_count,
        existing_count=saved.existing_count,skipped_count=saved.skipped_count,keyword=saved.keyword,
        imported_count=manifest['total_papers'] if manifest else 0,
        new_count=manifest['counts']['added'] if manifest else 0,
        failed_count=job.failed,progress=progress,error=job.error,
        next_retry_at=job.next_retry_at,background_task=view(task) if task else None,**batch_labels(job))


def create_online_router(db_session,admin):
    router=APIRouter(prefix='/api/admin/online-collections',dependencies=[Depends(admin)])
    @router.post('',status_code=202)
    def create(body:OnlineInput,db=Depends(db_session)):
        try:
            job,replay=queue_online(db,body);return online_view(db,job.id)|{'replay':replay}
        except (ValueError,IntegrityError) as exc:
            db.rollback();raise HTTPException(409,'该条件暂不能采集，请核对来源启用状态、年份或正在运行的任务' if isinstance(exc,IntegrityError) else str(exc)) from exc
    @router.get('/{identifier}')
    def read(identifier:int,db=Depends(db_session)):
        try:return online_view(db,identifier)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    return router
