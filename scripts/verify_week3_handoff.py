"""Real two-batch A acceptance and B's existing PaperInput/extractor compatibility check."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
from sqlalchemy import select,func
from app.models import database,Paper
from app.ingest import openalex_work_row,normalize_doi
from app.formal_batches import queue_batch,process_batch,batch_manifest,withdraw_batch,effective_state,export_json
from src.knowledge_builder.models import PaperInput
from src.knowledge_builder.extraction import extract_candidates,load_vocabulary,validate_result


def main():
 p=argparse.ArgumentParser();p.add_argument('--collection',type=Path,required=True);p.add_argument('--original-openalex',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False)
 full=json.loads((a.collection/'formal-input.json').read_text());fresh={r['row']['source_id']:r for r in full['records'] if r['source']=='openalex' and r['row'].get('abstract')}
 dblp={r['row']['doi']:r for r in full['records'] if r['source']=='dblp' and r['row'].get('doi')}
 old={work['id']:work for line in a.original_openalex.read_text().splitlines() if line.strip() for work in [json.loads(line)] if work.get('abstract_inverted_index') and work['id'] in fresh}
 identifiers=sorted(old)[:30]
 if len(identifiers)!=30:raise ValueError('Need 30 shared real source identities for the acceptance corpus')
 def records(ids,previous=False):
  result=[]
  for identifier in ids:
   row=openalex_work_row(old[identifier],'CVPR',2024) if previous else fresh[identifier]['row']
   result.append({'source':'openalex','row':row})
   doi=normalize_doi(row.get('doi'))
   if doi in dblp:result.append(dblp[doi])
  return result
 report={'data_origin':'actual frozen OpenAlex records and current DBLP official metadata; second batch includes five unchanged re-sent records, five refreshed records and ten new records; no fabricated metadata','scope':{'venue':'CVPR','year':2024},'b_runtime_service_connected':False}
 vocabulary=load_vocabulary()
 with tempfile.TemporaryDirectory() as temp:
  factory=database('sqlite:///'+str(Path(temp)/'acceptance.db'))
  try:
   with factory() as db:
    first,_=queue_batch(db,'week3-real-first','CVPR',2024,records(identifiers[:20],True));one=process_batch(db,first);export_json(one,a.output/'01-first-batch.json')
    ids_before=one['stable_papers'];replayed,replay=queue_batch(db,'week3-real-first','CVPR',2024,records(identifiers[:20],True));assert replay and replayed.id==first.id
    assert batch_manifest(db,first.id)['stable_papers']==ids_before
    second,_=queue_batch(db,'week3-real-second','CVPR',2024,records(identifiers[10:15],True)+records(identifiers[15:]));two=process_batch(db,second);export_json(two,a.output/'02-second-batch.json')
    state=effective_state(db);assert state['paper_count']==30
    before_inputs={item['paper_id']:item['input'] for item in state['papers']}
    extraction_counts=[]
    for envelope in [one,two]:
     for raw in envelope['items']:
      paper=PaperInput(**raw);result=extract_candidates(paper,vocabulary);validate_result(paper,result)
      extraction_counts.append({'paper_id':paper.openalex_id,'entities':len(result.entities),'relations':len(result.relations)})
    export_json(state,a.output/'03-effective-before-withdrawal.json')
    withdrawal=withdraw_batch(db,second.id,'Acceptance: withdraw second batch and retain the first batch');export_json(withdrawal,a.output/'04-second-batch-withdrawal.json')
    after=effective_state(db);assert after['paper_count']==20
    assert len([x for x in withdrawal['changes']['withdrawn'] if x['still_effective']])==10
    assert len([x for x in withdrawal['changes']['withdrawn'] if not x['still_effective']])==10
    assert db.scalar(select(func.count()).select_from(Paper))==30
    assert batch_manifest(db,first.id)['stable_papers']==ids_before
    export_json(after,a.output/'05-effective-after-withdrawal.json')
    # Real B extraction still works for the effective input set after withdrawal.
    for item in after['papers']:
     paper=PaperInput(**item['input']);validate_result(paper,extract_candidates(paper,vocabulary))
    report.update({'first':{'batch_code':one['batch_code'],'papers':one['total_papers'],'counts':one['counts']},
     'second':{'batch_code':two['batch_code'],'papers':two['total_papers'],'counts':two['counts']},
     'effective_before':30,'effective_after':20,'shared_retained':10,'second_only_removed':10,'stable_ids_preserved':True,'same_batch_replay_stable':True,
     'b_paperinput_and_extraction_checks':len(extraction_counts)+len(after['papers']),'b_candidates':extraction_counts,
     'revision_before':state['revision'],'revision_after':after['revision']})
  finally:factory.kw['bind'].dispose()
 export_json(report,a.output/'acceptance-results.json')
 print(json.dumps({k:v for k,v in report.items() if k!='b_candidates'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
