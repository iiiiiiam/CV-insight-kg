"""Build an explicitly labelled demo database without rewriting an existing database."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from sqlalchemy import select
from .models import database,Paper,Source,ImportCandidate


def create_demo(path, cvpr_jsonl=None, *, paper_limit=420, reserve_db=None):
    if paper_limit < 80:
        raise ValueError('Keep at least the 80 shared sample papers in the preview')
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
            from .paths import PROJECT_ROOT
            cvpr_file=Path(cvpr_jsonl) if cvpr_jsonl else PROJECT_ROOT/'examples/cvpr_2024_full/cvpr_2024.jsonl'
            if cvpr_jsonl or cvpr_file.exists():
                from .reserve import stage_openalex
                # Keep the entire input available for later manual imports; only a
                # small subset belongs to the initial preview collection.
                stage_openalex(db,cvpr_file,'CVPR',2024)
                imported=len(list(db.scalars(select(Paper.id).where(research_paper_scope()))))
                with cvpr_file.open(encoding='utf-8') as handle:
                    for line in handle:
                        if not line.strip():continue
                        work=json.loads(line)
                        if ((work.get('primary_location') or {}).get('source') or {}).get('id')!='https://openalex.org/S4210176548':
                            raise ValueError('Demo input is not a verified CVPR source')
                        row=openalex_work_row(work,'CVPR',2024)
                        if imported >= paper_limit:continue
                        if is_front_matter(row):continue
                        existing=db.scalar(select(Paper.id).where(Paper.openalex_id==row['source_id']))
                        upsert_paper(db,row,'openalex')
                        if existing is None:imported+=1
                db.commit()
            reserve_file=PROJECT_ROOT/'examples/supplementary_pool/iccv_2023.jsonl'
            if reserve_file.exists():
                from .batch_import import checked_rows
                from .reserve import stage_openalex
                checked_rows(reserve_file,'ICCV',2023,'openalex')
                stage_openalex(db,reserve_file,'ICCV',2023)
            if reserve_db:
                # Restore every candidate from the previous preview without its
                # old task claim. Existing papers are excluded by available_scope.
                source=Path(reserve_db).resolve()
                with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as previous:
                    previous.row_factory=sqlite3.Row
                    known=set(db.execute(select(ImportCandidate.source,ImportCandidate.source_id)).all())
                    for record in previous.execute('SELECT * FROM import_candidates ORDER BY id'):
                        values=dict(record)
                        identity=(values['source'],values['source_id'])
                        if identity in known:continue
                        values.pop('id');values['claimed_job_id']=None
                        values['created_at']=datetime.fromisoformat(values['created_at'])
                        db.add(ImportCandidate(**values));known.add(identity)
                db.commit()
            from .demo_presentation import rebuild_history
            rebuild_history(db)
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
    parser.add_argument('--paper-limit',type=int,default=420)
    parser.add_argument('--reserve-db',type=Path,help='Retain every supplementary candidate from an existing demo DB')
    args=parser.parse_args();print(create_demo(args.output,args.cvpr_jsonl,paper_limit=args.paper_limit,reserve_db=args.reserve_db))

if __name__=='__main__':main()
