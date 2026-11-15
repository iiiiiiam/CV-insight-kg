"""A-only formal batch endpoints; all use the existing A administrator boundary."""
from fastapi import APIRouter,Depends,HTTPException,Query
from pydantic import BaseModel,Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select,func
from .models import BatchLedger,Job
from .formal_batches import code,queue_batch,batch_manifest,withdraw_batch,effective_state


class FormalInput(BaseModel):
    batch_key:str=Field(min_length=1,max_length=180)
    venue:str
    year:int
    records:list[dict]=Field(min_length=1,max_length=20000)


class WithdrawInput(BaseModel):
    reason:str=Field(min_length=1,max_length=2000)


def create_formal_router(db_session,admin):
    router=APIRouter(prefix='/api/admin/formal',dependencies=[Depends(admin)])
    @router.post('/batches',status_code=201)
    def create(body:FormalInput,db=Depends(db_session)):
        try:
            job,replay=queue_batch(db,body.batch_key,body.venue,body.year,body.records)
            return {**batch_manifest(db,job.id),'replay':replay}
        except IntegrityError as exc:raise HTTPException(409,'Another task or batch key is already active') from exc
        except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    @router.get('/batches')
    def listing(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),db=Depends(db_session)):
        rows=db.execute(select(BatchLedger,Job).join(Job,Job.id==BatchLedger.job_id).order_by(Job.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
        return {'format_version':'a-batch-list/1','page':page,'page_size':page_size,'total':db.scalar(select(func.count()).select_from(BatchLedger)),
            'items':[{'batch_id':job.id,'batch_code':code(job.id),'batch_key':ledger.batch_key,'dataset_id':ledger.batch_key,
                'status':job.status,'state':'withdrawn' if ledger.withdrawn else 'active','input_revision':ledger.input_sha256,
                'created_at':job.created_at,'withdrawn_at':ledger.withdrawn_at} for ledger,job in rows]}
    @router.get('/effective')
    def effective(db=Depends(db_session)):
        try:return effective_state(db)
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    @router.get('/batches/{job_id}')
    def read(job_id:int,db=Depends(db_session)):
        try:return batch_manifest(db,job_id)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    @router.post('/batches/{job_id}/withdraw')
    def withdraw(job_id:int,body:WithdrawInput,db=Depends(db_session)):
        try:return withdraw_batch(db,job_id,body.reason)
        except LookupError as exc:raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    return router
