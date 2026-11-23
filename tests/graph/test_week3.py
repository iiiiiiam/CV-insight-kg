import os,json
from pathlib import Path
import pytest
from src.graph_query.search import normalize
from test_neo4j import repo


def test_normalization_alias_and_legacy_values():
 assert 'method:term:yolo' in normalize({'method':['YOLO',' You Only Look Once ']})['method']
 assert normalize({'year':2024})['year']==[2024]
 assert normalize({'author':['  Yi   Liu ','yi liu']})['author']==['yi liu']

@pytest.mark.skipif(not os.getenv('GRAPH_TEST_URI') or not os.getenv('WEEK3_EXPORTS'),reason='actual A→B exports and isolated Neo4j required')
def test_actual_a_b_c_week3(repo):
 from fastapi.testclient import TestClient
 from src.graph_query.api import create_app
 root=Path(os.environ['WEEK3_EXPORTS']);docs=[json.loads((root/f).read_text(encoding='utf-8')) for f in ['first-effective.json','merged-effective.json','withdrawn-effective.json','empty-effective.json']]
 assert [d['counts']['papers'] for d in docs]==[20,30,20,0]
 ids=[];expected_sets=[]
 for d in docs:
  result=repo.ingest_effective(d);bid=result['id'];assert repo.ingest_effective(d)['replay'];repo.publish(bid,repo.batch(bid)['active_batch_id']);ids.append(bid)
  expected={'paper:'+p['input']['openalex_id'] for p in d['papers']};expected_sets.append(expected)
  assert repo.papers({})['total']==len(expected)
  assert repo.statistics({},bid)['paper_count']==len(expected)
  pages=[repo.papers({},bid,page=i,page_size=7)['items'] for i in range(1,(len(expected)+6)//7+1)]
  actual=[n['id'] for page in pages for n in page];assert len(actual)==len(set(actual))==len(expected);assert set(actual)==expected
 assert expected_sets[0]==expected_sets[2];assert len(expected_sets[1]-expected_sets[2])==10
 import copy
 bad=copy.deepcopy(docs[0]);bad['counts']['papers']+=1
 with pytest.raises(ValueError):repo.ingest_effective(bad)
 from src.graph_query.repository import GraphError
 with pytest.raises(GraphError):repo.publish(ids[0],'not-current')
 assert repo.papers({})['batch_id']==ids[-1]
 for bid,count in zip(ids,[20,30,20,0]):assert repo.papers({},bid)['total']==count
 first={p['input']['openalex_id']:p['input'] for p in docs[0]['papers']};restored={p['input']['openalex_id']:p['input'] for p in docs[2]['papers']};assert first==restored
 bid=ids[1];d=docs[1];checks=[]
 for kind in ['author','institution','topic','method','task','dataset']:
  pool=sorted({i['content']['key'] for p in d['papers'] for i in p['entities'] if i['content']['kind']==kind})[:2]
  if not pool:continue
  expected={'paper:'+p['input']['openalex_id'] for p in d['papers'] if any(i['content']['kind']==kind and i['content']['key'] in pool for i in p['entities'])}
  assert {n['id'] for n in repo.papers({kind:pool},bid,page_size=100)['items']}==expected
  checks.append(kind)
 kinds=['author','institution','topic','method','task','dataset']
 anchor=max(d['papers'],key=lambda p:len({e['content']['kind'] for e in p['entities']}))
 combination={k:[next((e['content']['key'] for e in anchor['entities'] if e['content']['kind']==k),'nonexistent-id')] for k in kinds}
 expected={'paper:'+p['input']['openalex_id'] for p in d['papers'] if all(any(e['content']['kind']==k and e['content']['key'] in values for e in p['entities']) for k,values in combination.items())}
 rows=repo.papers(combination,bid,page_size=100)
 assert rows['total']==len(expected) and {n['id'] for n in rows['items']}==expected
 # Explicit multi-value OR plus AND on two different entity dimensions.
 authors=sorted({e['content']['key'] for p in d['papers'] for e in p['entities'] if e['content']['kind']=='author'})[:2]
 methods=sorted({e['content']['key'] for p in d['papers'] for e in p['entities'] if e['content']['kind']=='method'})[:2]
 expected={'paper:'+p['input']['openalex_id'] for p in d['papers'] if any(e['content']['key'] in authors for e in p['entities']) and any(e['content']['key'] in methods for e in p['entities'])}
 assert {n['id'] for n in repo.papers({'author':authors,'method':methods},bid,page_size=100)['items']}==expected
 years=sorted({p['input']['year'] for p in d['papers']});author=next(i['content']['key'] for p in d['papers'] for i in p['entities'] if i['content']['kind']=='author')
 expected={'paper:'+p['input']['openalex_id'] for p in d['papers'] if any(r['content']['kind']=='has_author' and r['content']['target']==author for r in p['relations'])}
 result=repo.papers({'author':[author],'year':years,'venue':['CVPR','ICCV']},bid,page_size=100)
 assert {n['id'] for n in result['items']}==expected
 assert repo.author_profile(author,bid)['papers']['total']==len(expected)
 paper=result['items'][0];assert paper['citation_count'] is None and paper['source_updated_at'] is None;assert paper['authors'] and paper['venue'];assert paper['knowledge_exported_at'] and paper['graph_published_at']
 detail=repo.detail(paper['id'],bid)['node'];assert detail['metadata'] and detail['data_revision']==docs[1]['revision']
 dirs={c['source_id'] for p in d['papers'] for c in p['source_classifications'] if c['kind']=='research_direction'}
 for direction in dirs:
  expected={'paper:'+p['input']['openalex_id'] for p in d['papers'] if any(c.get('source_id')==direction for c in p['source_classifications'])}
  assert {n['id'] for n in repo.papers({'direction':[direction]},bid,page_size=100)['items']}==expected
 with TestClient(create_app(repo,admin_token='test')) as c:
  response=c.get('/api/research/papers',params=[('batch_id',bid),('author',author),('year',str(years[0])),('year',str(years[-1]))]);assert response.status_code==200
  assert c.get('/api/research/papers?year=1800').status_code==422
 report=dict(counts=[20,30,20,0],batch_ids=ids,dimension_checks=checks,direction_ids=sorted(dirs),shared_inputs_restored=True,source='actual A handoff files → unmodified B reference BatchRegistry/effective exporter (offline) → C → isolated Neo4j; not live team HTTP/UI integration')
 Path(os.getenv('WEEK3_REPORT','docs/graph/week3-results.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
