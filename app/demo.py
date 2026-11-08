"""Build an explicitly labelled demo database without rewriting an existing database."""
import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
from collections import defaultdict
from sqlalchemy import select
from .models import database,Job,JobEvent,Paper,PaperSource,PaperBatch,Source,now


def create_demo(path, cvpr_jsonl=None):
    path=Path(path).resolve()
    if path.exists():
        raise ValueError('Demo destination exists; existing data is preserved')
    path.parent.mkdir(parents=True,exist_ok=True)
    build=path.with_suffix('.building.db')
    if build.exists():
        raise ValueError('An unfinished demo build exists; inspect it before using a different destination')
    factory=database('sqlite:///'+str(build))
    try:
        from .datasets import import_sample
        from .additional_samples import DATASETS,import_additional
        from .ingest import upsert_paper,openalex_work_row
        from .paper_quality import is_front_matter,research_paper_scope
        with factory() as db:
            db.add_all([Source(name=s) for s in ('cvf','ecva','openalex','dblp')]);db.commit()
            import_sample(db)
            for dataset in DATASETS:import_additional(db,dataset)
            if cvpr_jsonl:
                with Path(cvpr_jsonl).open(encoding='utf-8') as handle:
                    for line in handle:
                        work=json.loads(line)
                        if ((work.get('primary_location') or {}).get('source') or {}).get('id')!='https://openalex.org/S4210176548':
                            raise ValueError('Demo input is not a verified CVPR source')
                        row=openalex_work_row(work,'CVPR',2024)
                        if not is_front_matter(row):upsert_paper(db,row,'openalex')
                db.commit()
            from .paths import PROJECT_ROOT
            reserve_file=PROJECT_ROOT/'examples/supplementary_pool/iccv_2023.jsonl'
            if reserve_file.exists():
                from .batch_import import checked_rows
                from .reserve import stage_openalex
                checked_rows(reserve_file,'ICCV',2023,'openalex')
                stage_openalex(db,reserve_file,'ICCV',2023)
            for job in db.scalars(select(Job)):job.kind='archive'
            groups=defaultdict(list)
            for paper in db.scalars(select(Paper).where(research_paper_scope()).order_by(Paper.id)):
                sources=set(db.scalars(select(PaperSource.source).where(PaperSource.paper_id==paper.id)))
                source='ecva' if 'ecva' in sources else 'cvf' if 'cvf' in sources else 'openalex'
                groups[(paper.venue,paper.year,source)].append(paper)
            for (venue,year,source),papers in groups.items():
                weights=[8,12,9,15,11,17,13,18,16,22,19,25,21,28]
                counts=[len(papers)*weight//sum(weights) for weight in weights]
                for i in range(len(papers)-sum(counts)):counts[(13-i)%14]+=1
                offset=0
                for i,count in enumerate(counts):
                    if not count:continue
                    day=datetime.combine(now().date()-timedelta(days=13-i),datetime.min.time())+timedelta(hours=9)
                    job=Job(venue=venue,year=year,source=source,kind='demo',dataset_id=f'demo-{venue}-{day.date()}',status='succeeded',stage='done',attempted=count,succeeded=count,failed=0,created_at=day,started_at=day,finished_at=day+timedelta(minutes=8))
                    db.add(job);db.flush()
                    for paper in papers[offset:offset+count]:
                        paper.first_seen_at=day
                        db.add(PaperBatch(job_id=job.id,paper_id=paper.id,is_new=True,imported_at=day))
                    db.add(JobEvent(job_id=job.id,stage='done',level='info',message='演示批次：真实论文按模拟日期分批导入。',created_at=day))
                    offset+=count
            db.commit()
        factory.kw['bind'].dispose()
        build.replace(path)
    except BaseException:
        factory.kw['bind'].dispose()
        raise
    return path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--cvpr-jsonl',type=Path)
    args=parser.parse_args();print(create_demo(args.output,args.cvpr_jsonl))

if __name__=='__main__':main()
