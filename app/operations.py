"""A-owned quality reports and version-bound downstream receipts."""
import json
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import Base,Job,Paper,now
from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import Integer,String,Text,DateTime,ForeignKey,UniqueConstraint,func
from .paper_quality import research_paper_scope
from .formal_batches import batch_manifest
from .formal_collection import load_baseline
from .paths import configured_path

class HandoffReceipt(Base):
    __tablename__='a_handoff_receipts'
    id:Mapped[int]=mapped_column(primary_key=True)
    job_id:Mapped[int]=mapped_column(ForeignKey('jobs.id'),index=True)
    revision:Mapped[str]=mapped_column(String(64))
    recipient:Mapped[str]=mapped_column(String(64))
    status:Mapped[str]=mapped_column(String(20))
    message:Mapped[str]=mapped_column(Text,default='')
    snapshot_revision:Mapped[str|None]=mapped_column(String(200))
    updated_at:Mapped[object]=mapped_column(DateTime,default=now,onupdate=now)
    __table_args__=(UniqueConstraint('job_id','revision','recipient',name='uq_a_receipt'),)

class ReceiptInput(BaseModel):
    batch_revision:str=Field(pattern='^[0-9a-f]{64}$')
    recipient:str=Field(default='B',pattern='^[A-Za-z0-9._-]{1,64}$')
    status:str=Field(pattern='^(received|processed|failed)$')
    message:str=Field(default='',max_length=2000)
    snapshot_revision:str|None=Field(default=None,max_length=200)

def quality(db):
    from .models import PaperSource
    papers=db.scalars(select(Paper).where(research_paper_scope()).order_by(Paper.id)).all()
    sourced=set(db.scalars(select(PaperSource.paper_id)))
    issues=[]
    for p in papers:
        missing=[name for name,valid in [('abstract',bool((p.abstract or '').strip())),('doi',bool(p.doi)),('authors',bool(json.loads(p.authors_json))),('source',p.id in sourced)] if not valid]
        if missing:issues.append({'id':p.id,'title':p.title,'venue':p.venue,'year':p.year,'missing':missing})
    coverage=[]
    roots={configured_path('A_COLLECTION_ROOT','data/week3/collection')}
    for root in sorted(roots):
        for path in sorted(root.glob('*/baseline.json')):
            try:
                baseline=load_baseline(path)
                report_path=path.with_name('coverage-reviewed.json')
                if not report_path.exists():report_path=path.with_name('coverage.json')
                report=json.loads(report_path.read_text())
                if report.get('baseline_revision')!=baseline['revision']:raise ValueError('Coverage baseline revision mismatch')
                coverage.append(report)
            except (ValueError,OSError,KeyError) as exc:
                coverage.append({'scope':path.parent.name,'error':str(exc)})
    return {'total_papers':len(papers),'issue_count':len(issues),'issues':issues,'coverage':coverage}

def create_operations_router(db_session,admin):
    router=APIRouter(prefix='/api/admin',dependencies=[Depends(admin)])
    @router.get('/jobs/{job_id}/records')
    def records(job_id:int,status:str|None=Query(None,pattern='^(pending|succeeded|failed|skipped)$'),page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),db=Depends(db_session)):
        from .models import JobRecord,CvfRecord
        job=db.get(Job,job_id)
        if job is None:raise HTTPException(404,'Job not found')
        if db.scalar(select(JobRecord.id).where(JobRecord.job_id==job_id).limit(1)) is None:
            legacy_scope=[CvfRecord.job_id==job_id]
            if status:legacy_scope.append(CvfRecord.status==status)
            total=db.scalar(select(func.count()).select_from(CvfRecord).where(*legacy_scope))
            values=db.scalars(select(CvfRecord).where(*legacy_scope).order_by(CvfRecord.id).offset((page-1)*page_size).limit(page_size)).all()
            return {'job_id':job_id,'total':total,'page':page,'page_size':page_size,'items':[{'id':r.id,'source':job.source,'source_id':r.source_id,'status':r.status,'stage':'cvf','attempts':None,'error':None,'updated_at':job.updated_at} for r in values]}
        scope=[JobRecord.job_id==job_id]
        if status:scope.append(JobRecord.status==status)
        total=db.scalar(select(func.count()).select_from(JobRecord).where(*scope))
        values=db.scalars(select(JobRecord).where(*scope).order_by(JobRecord.id).offset((page-1)*page_size).limit(page_size)).all()
        return {'job_id':job_id,'total':total,'page':page,'page_size':page_size,'items':[{'id':r.id,'source':r.source,'source_id':r.source_id,'status':r.status,'stage':r.stage,'attempts':r.attempts,'error':r.error,'updated_at':r.updated_at} for r in values]}
    @router.get('/quality')
    def read_quality(db=Depends(db_session)):return quality(db)
    @router.get('/formal/batches/{job_id}/receipts')
    def receipts(job_id:int,db=Depends(db_session)):
        try:manifest=batch_manifest(db,job_id)
        except LookupError as exc:raise HTTPException(404,str(exc))
        values=db.scalars(select(HandoffReceipt).where(HandoffReceipt.job_id==job_id).order_by(HandoffReceipt.id.desc())).all()
        return {'batch_revision':manifest['batch_revision'],'state':manifest['state'],'items':[{'recipient':v.recipient,'status':v.status,'message':v.message,'snapshot_revision':v.snapshot_revision,'updated_at':v.updated_at,'batch_revision':v.revision,'current':v.revision==manifest['batch_revision']} for v in values]}
    @router.post('/formal/batches/{job_id}/receipts')
    def receive(job_id:int,body:ReceiptInput,db=Depends(db_session)):
        try:manifest=batch_manifest(db,job_id)
        except LookupError as exc:raise HTTPException(404,str(exc))
        if manifest['status'] in ('queued','running') or manifest['batch_revision']!=body.batch_revision:raise HTTPException(409,'Batch changed or still running; refresh its revision')
        row=db.scalar(select(HandoffReceipt).where(HandoffReceipt.job_id==job_id,HandoffReceipt.revision==body.batch_revision,HandoffReceipt.recipient==body.recipient))
        if row is None:row=HandoffReceipt(job_id=job_id,revision=body.batch_revision,recipient=body.recipient);db.add(row)
        if row.status=='processed' and body.status=='received':raise HTTPException(409,'A processed receipt cannot regress to received')
        row.status=body.status;row.message=body.message;row.snapshot_revision=body.snapshot_revision;row.updated_at=now()
        try:db.commit()
        except IntegrityError as exc:
            db.rollback();raise HTTPException(409,'Receipt updated concurrently; refresh and retry') from exc
        return receipts(job_id,db)
    return router
