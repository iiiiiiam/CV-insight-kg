"""A real supplementary collection: papers enter the main library only on import."""
import argparse
import hashlib
import json
from pathlib import Path
from sqlalchemy import select,func,exists,update
from .models import ImportCandidate as Candidate,Paper,PaperSource,Source,Job
from .ingest import openalex_work_row,normalize_title
from .paper_quality import is_front_matter
from .pipeline import save_snapshot
from scripts.fetch_openalex_batch import SOURCES


def available_scope():
    known_source=exists(select(PaperSource.id).where(PaperSource.source==Candidate.source,PaperSource.source_id==Candidate.source_id)).correlate(Candidate)
    known_id=exists(select(Paper.id).where(Paper.openalex_id==Candidate.source_id)).correlate(Candidate)
    known_doi=exists(select(Paper.id).where(Paper.doi==Candidate.doi)).correlate(Candidate)
    known_title=exists(select(Paper.id).where(Paper.venue==Candidate.venue,Paper.year==Candidate.year,Paper.title_normalized==Candidate.title_normalized)).correlate(Candidate)
    return (Candidate.claimed_job_id.is_(None),~known_source,~known_id,~known_doi,~known_title)


def stage_openalex(db,path,venue,year):
    if venue not in SOURCES:raise ValueError('Supported supplementary OpenAlex sources: CVPR and ICCV')
    body=Path(path).read_bytes();digest=hashlib.sha256(body).hexdigest()
    seen=set();values=[];filtered=0
    for line in body.decode('utf-8').splitlines():
        if not line.strip():continue
        work=json.loads(line)
        if ((work.get('primary_location') or {}).get('source') or {}).get('id')!='https://openalex.org/'+SOURCES[venue]:
            raise ValueError('Supplementary file has an unexpected conference source')
        row=openalex_work_row(work,venue,year)
        if row['source_id'] in seen:raise ValueError('Duplicate source ID in supplementary file')
        seen.add(row['source_id'])
        if is_front_matter(row) or not row.get('abstract'):
            filtered+=1;continue
        if not isinstance(row['authors'],list) or any(not isinstance(name,str) for name in row['authors']):
            raise ValueError('Invalid author names in supplementary file')
        values.append((row,work))
    if not values:raise ValueError('No valid papers with abstracts in supplementary file')
    added=0
    try:
        for row,work in values:
            if db.scalar(select(Candidate.id).where(Candidate.source=='openalex',Candidate.source_id==row['source_id'])) is None:
                db.add(Candidate(source='openalex',source_id=row['source_id'],venue=venue,year=year,title=row['title'],title_normalized=normalize_title(row['title']),doi=row.get('doi'),payload_json=json.dumps(work,ensure_ascii=False),input_sha256=digest));added+=1
        db.commit()
    except BaseException:
        db.rollback();raise
    return {'staged':added,'valid':len(values),'filtered':filtered,'input_sha256':digest}


def summary(db):
    groups=db.execute(select(Candidate.venue,Candidate.year,Candidate.source,func.count(Candidate.id)).group_by(Candidate.venue,Candidate.year,Candidate.source).order_by(Candidate.venue,Candidate.year.desc())).all()
    items=[]
    for venue,year,source,total in groups:
        scope=(Candidate.venue==venue,Candidate.year==year,Candidate.source==source)
        remaining=db.scalar(select(func.count(Candidate.id)).where(*scope,*available_scope())) or 0
        items.append({'venue':venue,'year':year,'source':source,'total':total,'available':remaining})
    return {'items':items,'available':sum(item['available'] for item in items)}


def queue_import(db,venue,year,source,count):
    if not 1<=count<=100:raise ValueError('Choose between 1 and 100 papers per import')
    configured=db.scalar(select(Source).where(Source.name==source))
    if not configured or not configured.enabled:raise ValueError('该数据来源已停用，请先启用后再导入')
    candidates=list(db.scalars(select(Candidate).where(Candidate.venue==venue,Candidate.year==year,Candidate.source==source,*available_scope()).order_by(Candidate.id).limit(count)))
    if not candidates:raise ValueError('所选范围没有待导入的新论文，请选择其他范围')
    job=Job(venue=venue,year=year,source=source,kind='reserve',dataset_id=f'reserve:{venue}:{year}',status='queued',active_key=f'{venue}:{year}')
    try:
        db.add(job);db.flush()
        ids=[item.id for item in candidates]
        result=db.execute(update(Candidate).where(Candidate.id.in_(ids),Candidate.claimed_job_id.is_(None)).values(claimed_job_id=job.id))
        if result.rowcount!=len(ids):raise ValueError('这批论文已被其他任务选中，请刷新后重试')
        rows=[{'source_id':item.source_id,'raw':json.loads(item.payload_json),'openalex_work':True} for item in candidates]
        save_snapshot(db,job,rows,source)
    except BaseException:
        db.rollback();raise
    return job,len(candidates)


def main():
    parser=argparse.ArgumentParser(description='Prepare a supplementary library without importing into the main paper collection')
    parser.add_argument('venue',choices=SOURCES);parser.add_argument('year',type=int);parser.add_argument('jsonl',type=Path)
    args=parser.parse_args()
    from .db import SessionLocal
    with SessionLocal() as db:
        result=stage_openalex(db,args.jsonl,args.venue,args.year);result['reserve']=summary(db)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
