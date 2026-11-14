"""Durable A batches, stable identity, withdrawal and additive a-paperinput/1 handoff metadata."""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import re
from pathlib import Path
from sqlalchemy import select, or_, update
from sqlalchemy.exc import IntegrityError
from .models import BatchScopeLock, BatchLedger, BatchPaperVersion, StablePaper, Job, JobEvent, JobRecord, Paper, PaperBatch, PaperSource, now
from .ingest import upsert_paper, normalize_title, normalize_doi
from .pipeline import safe_error
from .batch_labels import batch_labels


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def code(job_id):
    return f'BATCH-{job_id:06d}'


def paper_content(paper):
    return {key:getattr(paper,key) for key in ('title','abstract','year','venue','doi','openalex_id','dblp_key','cited_by_count','source_url')} | {'authors':json.loads(paper.authors_json)}


def prior_paper(db,row,source):
    provenance=db.scalar(select(PaperSource).where(PaperSource.source==source,PaperSource.source_id==row['source_id']))
    if provenance:return db.get(Paper,provenance.paper_id)
    conditions=[]
    if row.get('doi'):conditions.append(Paper.doi==normalize_doi(row['doi']))
    if source=='openalex':conditions.append(Paper.openalex_id==row['source_id'])
    if row.get('dblp_key'):conditions.append(Paper.dblp_key==row['dblp_key'])
    if conditions:
        found=db.scalar(select(Paper).where(or_(*conditions)))
        if found:return found
    matches=db.scalars(select(Paper).where(Paper.title_normalized==normalize_title(row['title']),Paper.venue==row['venue'],Paper.year==row['year']).limit(2)).all()
    return matches[0] if len(matches)==1 else None


def latest_version(db,paper_id,exclude=None):
    query=select(BatchPaperVersion).join(BatchLedger,BatchLedger.job_id==BatchPaperVersion.job_id).where(BatchPaperVersion.paper_id==paper_id,BatchLedger.withdrawn.is_(False))
    if exclude is not None:query=query.where(BatchPaperVersion.job_id!=exclude)
    return db.scalar(query.order_by(BatchPaperVersion.job_id.desc()).limit(1))


def freeze_content(db,paper,batch_key):
    sources=db.scalars(select(PaperSource).where(PaperSource.paper_id==paper.id).order_by(PaperSource.source,PaperSource.source_id)).all()
    evidence=[{'source':s.source,'source_id':s.source_id,'source_url':s.source_url,'raw':json.loads(s.raw_json)} for s in sources]
    b_input=None
    for source in sources:
        if source.source=='openalex':
            from src.knowledge_builder.input_adapter import adapt_openalex_work
            try:b_input=asdict(adapt_openalex_work(json.loads(source.raw_json),venue=paper.venue,dataset_id=batch_key))
            except (KeyError,TypeError,ValueError):pass
    return {'paper':paper_content(paper),'input':b_input,'sources':evidence}


def lock_scope(db,venue,year):
    key=f'{venue}:{year}'
    if db.get(BatchScopeLock,key) is None:
        try:
            with db.begin_nested():db.add(BatchScopeLock(scope_key=key));db.flush()
        except IntegrityError:pass
    db.scalar(select(BatchScopeLock).where(BatchScopeLock.scope_key==key).with_for_update())


def queue_batch(db,batch_key,venue,year,records):
    if not isinstance(batch_key,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,179}',batch_key):raise ValueError('Invalid batch key')
    if venue not in ('CVPR','ICCV') or type(year)is not int or not 1980<=year<=now().year:raise ValueError('Invalid formal conference/year')
    if not records or len(records)>20000:raise ValueError('Batch must contain 1–20000 source records')
    identifiers=set()
    for record in records:
        source,row=record.get('source'),record.get('row')
        if source not in ('openalex','dblp') or not isinstance(row,dict):raise ValueError('Formal inputs must be DBLP/OpenAlex records')
        if (row.get('venue'),row.get('year'))!=(venue,year) or not isinstance(row.get('source_id'),str) or not row.get('source_id') or not row.get('title'):raise ValueError('Record identity/scope is invalid')
        if source=='openalex':
            from scripts.fetch_openalex_batch import SOURCES
            raw=row.get('raw',{})
            if raw.get('id')!=row['source_id'] or raw.get('publication_year')!=year or ((raw.get('primary_location') or {}).get('source') or {}).get('id')!='https://openalex.org/'+SOURCES[venue]:raise ValueError('OpenAlex evidence and normalized scope disagree')
            from .ingest import openalex_work_row
            if row!=openalex_work_row(raw,venue,year):raise ValueError('Normalized metadata differs from the frozen OpenAlex source')
        if source=='dblp' and (row.get('dblp_key')!=row['source_id'] or not row['source_id'].startswith('conf/'+venue.lower()+'/')):raise ValueError('DBLP evidence scope/identifier disagree')
        key=(source,row['source_id'])
        if key in identifiers:raise ValueError('Duplicate source record inside a batch')
        identifiers.add(key)
    lock_scope(db,venue,year)
    checksum=digest({'venue':venue,'year':year,'records':records})
    existing=db.scalar(select(BatchLedger).where(BatchLedger.batch_key==batch_key))
    if existing:
        if existing.input_sha256!=checksum:raise ValueError('Batch is immutable; use a new batch key for changed inputs')
        return db.get(Job,existing.job_id),True
    job=Job(venue=venue,year=year,source='openalex' if all(r['source']=='openalex' for r in records) else 'dblp',kind='formal',dataset_id=batch_key,status='queued',stage='queued',active_key=f'{venue}:{year}')
    try:
        db.add(job);db.flush()
        db.add(BatchLedger(job_id=job.id,batch_key=batch_key,input_sha256=checksum))
        db.add_all([JobRecord(job_id=job.id,source=r['source'],source_id=r['row']['source_id'],payload_json=canonical(r['row'])) for r in records])
        db.commit()
    except Exception:db.rollback();raise
    return job,False


def process_batch(db,job):
    ledger=db.get(BatchLedger,job.id)
    if ledger is None or ledger.withdrawn:raise ValueError('Missing or withdrawn formal batch')
    from .paper_quality import is_front_matter
    job.status='running';job.stage='upsert';job.started_at=job.started_at or now();job.finished_at=None;db.commit()
    records=db.scalars(select(JobRecord).where(JobRecord.job_id==job.id,JobRecord.status.not_in(('succeeded','skipped'))).order_by(JobRecord.id)).all()
    statuses=Counter(db.scalars(select(JobRecord.status).where(JobRecord.job_id==job.id)))
    for index,record in enumerate(records,1):
        previous_status=record.status
        record.attempts+=1
        try:
            with db.begin_nested():
                row=json.loads(record.payload_json)
                if is_front_matter(row):
                    record.status='skipped';record.stage='done';record.error='Non-paper proceedings material'
                else:
                    before=prior_paper(db,row,record.source)
                    before_id=before.id if before else None
                    before_json=canonical(paper_content(before)) if before else None
                    was_active=bool(before) and (db.get(StablePaper,before.id) is None or db.get(StablePaper,before.id).active)
                    paper=upsert_paper(db,row,record.source,job=job)
                    identity=db.get(StablePaper,paper.id)
                    if identity is None:
                        identity=StablePaper(paper_id=paper.id,stable_id='paper:'+hashlib.sha256(paper.canonical_key.encode()).hexdigest(),baseline_json=before_json if before_id==paper.id else None)
                        db.add(identity)
                    identity.active=True
                    content=freeze_content(db,paper,ledger.batch_key)
                    # Scope-local dataset_id and retrieval metadata do not make identical papers updates.
                    fingerprint=digest({'paper':content['paper'],'sources':content['sources']})
                    version=db.get(BatchPaperVersion,(job.id,paper.id))
                    previous=latest_version(db,paper.id,exclude=job.id)
                    old=before_json if previous is None else canonical(json.loads(previous.content_json)['paper'])
                    change='added' if before_id!=paper.id or not was_active else ('updated' if old!=canonical(content['paper']) or (previous is not None and previous.content_sha256!=fingerprint) else 'duplicate')
                    if version is None:
                        version=BatchPaperVersion(job_id=job.id,paper_id=paper.id,change_kind=change,content_sha256=fingerprint,content_json=canonical(content));db.add(version)
                    else:
                        if version.change_kind!='added' and change=='updated':version.change_kind='updated'
                        version.content_sha256=fingerprint;version.content_json=canonical(content)
                    if previous is not None and previous.job_id>job.id:
                        newer=json.loads(previous.content_json)['paper']
                        for key in ('title','abstract','cited_by_count','source_url'):setattr(paper,key,newer[key])
                        paper.authors_json=json.dumps(newer['authors'],ensure_ascii=False);paper.title_normalized=normalize_title(paper.title)
                    record.status='succeeded';record.stage='done';record.error=None
                    db.flush()
        except Exception as exc:
            record.status='failed';record.error=safe_error(exc)
            db.add(JobEvent(job_id=job.id,stage='upsert',level='error',message=record.error))
        record.updated_at=now();db.flush()
        statuses[previous_status]-=1;statuses[record.status]+=1
        job.succeeded=statuses['succeeded'];job.failed=statuses['failed'];job.skipped=statuses['skipped'];job.attempted=job.succeeded+job.failed+job.skipped;job.updated_at=now()
        if index%25==0 or index==len(records):db.commit()
        if job.attempted%250==0:print(f'{code(job.id)}: {job.attempted} source records processed',flush=True)
    job.status='partial' if job.failed else 'succeeded';job.stage='done';job.error=f'{job.failed} records failed' if job.failed else None;job.active_key=None;job.finished_at=now()
    db.add(JobEvent(job_id=job.id,stage='done',level='info',message=f'Formal batch complete: {job.succeeded} succeeded, {job.failed} failed'))
    db.commit()
    return batch_manifest(db,job.id)


def effective_state(db):
    if db.scalar(select(Job.id).join(BatchLedger,BatchLedger.job_id==Job.id).where(Job.status.in_(('queued','running'))).limit(1)) is not None:
        raise ValueError('Formal import is still running; wait before creating a complete effective set')
    identities=db.scalars(select(StablePaper).where(StablePaper.active.is_(True)).order_by(StablePaper.stable_id)).all()
    papers=[]
    for identity in identities:
        version=latest_version(db,identity.paper_id)
        if version:papers.append({'paper_id':identity.stable_id,'source_batch':code(version.job_id),'source_batch_key':db.get(BatchLedger,version.job_id).batch_key,**json.loads(version.content_json)})
    active=[code(j) for j in db.scalars(select(BatchLedger.job_id).where(BatchLedger.withdrawn.is_(False)).order_by(BatchLedger.job_id))]
    return {'format_version':'a-effective/1','revision':digest({'active_batches':active,'papers':papers}),'active_batches':active,'papers':papers,'paper_count':len(papers)}


def batch_manifest(db,job_id):
    ledger=db.get(BatchLedger,job_id);job=db.get(Job,job_id)
    if ledger is None:raise LookupError('Formal batch not found')
    versions=db.scalars(select(BatchPaperVersion).where(BatchPaperVersion.job_id==job_id).order_by(BatchPaperVersion.paper_id)).all()
    changes={'added':[],'duplicate':[],'updated':[],'withdrawn':[],'failed':[]}
    items=[];excluded=[];stable_papers=[]
    for version in versions:
        identity=db.get(StablePaper,version.paper_id);content=json.loads(version.content_json)
        stable_papers.append({'paper_id':identity.stable_id,'openalex_id':content['paper']['openalex_id'],'content_sha256':version.content_sha256,
            'sources':[{key:source.get(key) for key in ('source','source_id','source_url')}|{'raw_sha256':digest(source['raw'])} for source in content['sources']]})
        changes[version.change_kind].append(identity.stable_id)
        if ledger.withdrawn:
            surviving=db.scalars(select(BatchPaperVersion.job_id).join(BatchLedger,BatchLedger.job_id==BatchPaperVersion.job_id).where(BatchPaperVersion.paper_id==version.paper_id,BatchLedger.withdrawn.is_(False)).order_by(BatchPaperVersion.job_id)).all()
            changes['withdrawn'].append({'paper_id':identity.stable_id,'still_effective':identity.active,'remaining_batches':[code(j) for j in surviving],'remaining_batch_keys':[db.get(BatchLedger,j).batch_key for j in surviving],'baseline_effective':identity.baseline_json is not None})
        if content['input'] is not None:items.append(content['input'])
        else:excluded.append({'paper_id':version.paper_id,'title':content['paper']['title'],'stable_id':identity.stable_id,'paper':content['paper'],'sources':content['sources'],'reason':'No verified OpenAlex PaperInput; original source metadata is retained'})
    for record in db.scalars(select(JobRecord).where(JobRecord.job_id==job_id,JobRecord.status=='failed')):
        changes['failed'].append({'source':record.source,'source_id':record.source_id,'reason':record.error,'attempts':record.attempts})
    return {'format_version':'a-paperinput/1','batch_id':job_id,'batch_code':code(job_id),'dataset_id':ledger.batch_key,'batch_key':ledger.batch_key,
        'input_revision':ledger.input_sha256,'state':'withdrawn' if ledger.withdrawn else 'active','status':job.status,
        'withdrawal_reason':ledger.withdrawal_reason,'withdrawn_at':ledger.withdrawn_at.isoformat() if ledger.withdrawn_at else None,
        'total_papers':len(versions),'exported_papers':len(items),'excluded_papers':len(excluded),'items':items,'excluded':excluded,
        'counts':{name:len(values) for name,values in changes.items()},
        'batch_revision':digest({'input':ledger.input_sha256,'withdrawn':ledger.withdrawn,'content':[(v.paper_id,v.content_sha256) for v in versions],'failed':changes['failed']}),
        'changes':changes,'stable_papers':stable_papers,
        **batch_labels(job)}


def withdraw_batch(db,job_id,reason):
    ledger=db.get(BatchLedger,job_id);job=db.get(Job,job_id)
    if ledger is None:raise LookupError('Formal batch not found')
    lock_scope(db,job.venue,job.year);db.refresh(ledger)
    if not reason or not reason.strip():raise ValueError('Withdrawal reason is required')
    if ledger.withdrawn:return batch_manifest(db,job_id)
    if job.status in ('queued','running'):raise ValueError('Wait for the active task to finish before withdrawal')
    active=db.scalar(select(Job.id).where(Job.venue==job.venue,Job.year==job.year,Job.status.in_(('queued','running'))).limit(1))
    if active:raise ValueError('Another task for this conference/year is still active')
    ledger.withdrawn=True;ledger.withdrawal_reason=reason.strip();ledger.withdrawn_at=now();db.flush()
    removed,retained=[],[]
    for version in db.scalars(select(BatchPaperVersion).where(BatchPaperVersion.job_id==job_id)):
        identity=db.get(StablePaper,version.paper_id);was_active=identity.active;previous=latest_version(db,version.paper_id)
        content=json.loads(previous.content_json)['paper'] if previous else json.loads(identity.baseline_json) if identity.baseline_json else None
        if content is None:
            unmanaged=db.scalar(select(PaperBatch.job_id).outerjoin(BatchLedger,BatchLedger.job_id==PaperBatch.job_id).where(
                PaperBatch.paper_id==version.paper_id,PaperBatch.job_id!=job_id,BatchLedger.job_id.is_(None)).limit(1))
            if unmanaged is not None:
                content=paper_content(db.get(Paper,version.paper_id))
                identity.baseline_json=canonical(content)
        identity.active=content is not None
        if was_active:
            (retained if identity.active else removed).append(version.paper_id)
        if content:
            paper=db.get(Paper,version.paper_id)
            for key in ('title','abstract','cited_by_count','source_url'):setattr(paper,key,content[key])
            paper.authors_json=json.dumps(content['authors'],ensure_ascii=False);paper.title_normalized=normalize_title(paper.title);paper.updated_at=now()
    if job.kind=='reserve':
        from .models import ImportCandidate
        db.execute(update(ImportCandidate).where(ImportCandidate.claimed_job_id==job_id).values(claimed_job_id=None))
    from .models import BatchWithdrawalAudit
    db.add(BatchWithdrawalAudit(job_id=job_id,occurred_at=ledger.withdrawn_at,
        removed_json=canonical(removed),retained_json=canonical(retained)))
    db.add(JobEvent(job_id=job_id,stage='withdrawn',level='warning',message=reason.strip()));db.commit()
    return batch_manifest(db,job_id)


def export_json(value,path):
    path=Path(path)
    if path.exists() or path.with_suffix(path.suffix+'.sha256').exists():raise FileExistsError(path)
    body=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(body)
    path.with_suffix(path.suffix+'.sha256').write_text(hashlib.sha256(body).hexdigest()+'  '+path.name+'\n')
    return path


def main():
    parser=argparse.ArgumentParser(description='Formal A batch processing and checked B handoff')
    sub=parser.add_subparsers(dest='action',required=True)
    imp=sub.add_parser('import');imp.add_argument('file',type=Path);imp.add_argument('--key',required=True)
    for name in ('export','withdraw','retry'):
        cmd=sub.add_parser(name);cmd.add_argument('job_id',type=int)
        if name=='withdraw':cmd.add_argument('--reason',required=True)
        if name=='export':cmd.add_argument('output',type=Path)
    sub.add_parser('effective').add_argument('output',type=Path)
    args=parser.parse_args()
    from .db import SessionLocal
    from contextlib import nullcontext
    from .worker_lock import worker_lock
    guard=worker_lock(SessionLocal) if args.action in ('import','retry') else nullcontext()
    with guard,SessionLocal() as db:
        if args.action=='import':
            payload=json.loads(args.file.read_text(encoding='utf-8'));job,replay=queue_batch(db,args.key,payload['venue'],payload['year'],payload['records'])
            result=batch_manifest(db,job.id) if replay else process_batch(db,job);result['replay']=replay
        elif args.action=='withdraw':result=withdraw_batch(db,args.job_id,args.reason)
        elif args.action=='retry':result=process_batch(db,db.get(Job,args.job_id))
        else:
            result=effective_state(db) if args.action=='effective' else batch_manifest(db,args.job_id);export_json(result,args.output)
        print(json.dumps({k:v for k,v in result.items() if k not in ('items','papers','stable_papers','changes','excluded')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
