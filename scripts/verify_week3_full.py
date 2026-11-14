"""Import the six frozen real source snapshots into an explicitly isolated database."""
import argparse
import json
from pathlib import Path
from sqlalchemy import select,func
from app.models import database,Paper
from app.paper_quality import research_paper_scope
from app.formal_batches import queue_batch,process_batch,batch_manifest,effective_state


def main():
 p=argparse.ArgumentParser();p.add_argument('--collection',type=Path,required=True);p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true');a=p.parse_args()
 if a.database.exists() and not a.resume:raise ValueError('Use a new isolated database to avoid changing an existing run')
 a.database.parent.mkdir(parents=True,exist_ok=True)
 factory=database('sqlite:///'+str(a.database.resolve()));report={'scopes':[]}
 try:
  for path in sorted(a.collection.glob('*/formal-input.json')):
   payload=json.loads(path.read_text(encoding='utf-8'));key=f'week3-{payload["venue"].lower()}-{payload["year"]}'
   with factory() as db:
    job,_=queue_batch(db,key,payload['venue'],payload['year'],payload['records']);result=process_batch(db,job)
    replay,seen=queue_batch(db,key,payload['venue'],payload['year'],payload['records']);assert seen and replay.id==job.id
    result2=batch_manifest(db,job.id);assert result2['stable_papers']==result['stable_papers']
    item={'venue':payload['venue'],'year':payload['year'],'batch_id':job.id,'batch_code':result['batch_code'],'status':result['status'],'counts':result['counts'],'valid_papers':result['total_papers'],'exported':result['exported_papers'],'excluded':result['excluded_papers'],'replay_stable':True}
    report['scopes'].append(item);print('IMPORTED',json.dumps(item,ensure_ascii=False),flush=True)
  with factory() as db:
   report['effective_papers']=db.scalar(select(func.count()).select_from(Paper).where(research_paper_scope()))
   report['effective_revision']=effective_state(db)['revision']
  a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print('DONE',report['effective_papers'],flush=True)
 finally:factory.kw['bind'].dispose()

if __name__=='__main__':main()
