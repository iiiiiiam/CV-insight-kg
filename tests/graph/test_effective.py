import copy,json,os
from pathlib import Path
from collections import Counter
import pytest
import httpx
from src.graph_query.effective import validate_effective, project, revision
from src.graph_query.effective_source import FileEffectiveSource,HttpEffectiveSource

ROOT=Path(__file__).resolve().parents[2]

def sample():return json.loads((ROOT/'sample_data/graph/effective-minimal.json').read_text(encoding='utf-8'))

def seal(doc):
 c=Counter(i['provenance']['review_state'] for p in doc['papers'] for g in ('entities','relations') for i in p[g])
 doc['counts']=dict(papers=len(doc['papers']),entities=sum(len(p['entities']) for p in doc['papers']),relations=sum(len(p['relations']) for p in doc['papers']),review_states={s:c[s] for s in ('automatic','human_confirmed','human_corrected')})
 doc['revision']=revision(doc);return doc

def test_valid_projection_and_time_independence():
 d=sample();n,e=project(d)
 assert all(x['review_state']=='automatic' and 'reviewer' not in x for x in e)
 assert sum(len(json.loads(x['contexts_json'])) for x in n)==d['counts']['entities']
 d['generated_at']='2026-11-09T00:00:00Z';validate_effective(d)

@pytest.mark.parametrize('change',['checksum','counts','offset','provenance','endpoint','candidate','classification'])
def test_invalid_effective(change):
 d=sample();p=d['papers'][0]
 if change=='checksum':d['mode']='incremental'
 elif change=='counts':d['counts']['entities']+=1
 elif change=='offset':p['entities'][0]['evidence'][0]['quote']='fake quote';seal(d)
 elif change=='provenance':p['entities'][0]['provenance']['review_state']='confirmed';seal(d)
 elif change=='endpoint':p['relations'][0]['content']['target']='missing';seal(d)
 elif change=='candidate':p['relations'][0]['candidate_id']=p['entities'][0]['candidate_id'];seal(d)
 else:p['source_classifications'][0]['basis']='mentions_topic';seal(d)
 with pytest.raises(ValueError):validate_effective(d)

def test_http_source_contract_and_failures():
 d=sample();calls=[]
 def handle(req):
  calls.append(req);return httpx.Response(200,json=d,headers={'X-Knowledge-Revision':d['revision']})
 with httpx.Client(base_url='https://b.example',transport=httpx.MockTransport(handle)) as client:
  assert HttpEffectiveSource(client).load(d['revision'])==d
 assert calls[0].url.path=='/api/admin/knowledge/effective-export'
 assert calls[0].url.params['expected_revision']==d['revision']
 for code in (401,409,503,302):
  with httpx.Client(base_url='https://b.example',transport=httpx.MockTransport(lambda req:httpx.Response(code))) as client:
   with pytest.raises(ValueError):HttpEffectiveSource(client).load()
 with httpx.Client(base_url='https://b.example',transport=httpx.MockTransport(lambda req:httpx.Response(200,json=d))) as client:
  with pytest.raises(ValueError):HttpEffectiveSource(client).load()

@pytest.mark.skipif(not os.getenv('GRAPH_TEST_URI'),reason='isolated Neo4j required')
def test_effective_roundtrip():
 from src.graph_query.repository import GraphRepository
 from src.graph_query.api import create_app
 from fastapi.testclient import TestClient
 r=GraphRepository(os.environ['GRAPH_TEST_URI'],'neo4j',os.getenv('GRAPH_TEST_PASSWORD','test-password'))
 try:
  r.initialize();d=FileEffectiveSource(os.getenv('EFFECTIVE_TEST_FILE',ROOT/'sample_data/graph/effective-minimal.json')).load()
  out=r.ingest_effective(d);bid=out['id']
  assert out['paper_count']==d['counts']['papers'] and out['source_entity_count']==d['counts']['entities'] and out['relation_count']==d['counts']['relations']
  assert r.ingest_effective(d)['replay']
  regenerated=copy.deepcopy(d);regenerated['generated_at']='2026-11-09T00:00:00Z';assert r.ingest_effective(regenerated)['replay']
  active=r.batch(bid)['active_batch_id'];r.publish(bid,active)
  assert r.papers({},bid)['total']==len(d['papers'])
  paper=next(i['content']['key'] for i in d['papers'][0]['entities'] if i['content']['kind']=='paper')
  details=r.detail(paper,bid);assert details['node']['effective_partition']==d['papers'][0]
  assert all(e['review_state']=='automatic' for e in details['relations'])
  assert r.graph(paper,2,bid)['edges']
  stats=r.statistics({},bid);assert stats['paper_count']==len(d['papers']) and stats['basis']['relations']=='public_effective'
  assert stats['review_state_counts']==d['counts']['review_states']
  assert stats['distributions']['topic']['papers_with_confirmed_relation'] is None
  for kind in ('topic','method'):
   expected=sum(any(r['content']['kind']=='mentions_'+kind for r in p['relations']) for p in d['papers'])
   assert stats['distributions'][kind]['papers_with_effective_relation']==expected
  if len(d['papers'])==150:
   yi='author:https://openalex.org/A5100701079'
   profile=r.author_profile(yi,bid,page_size=1)
   assert profile['papers']['total']==1
   assert profile['papers']['items'][0]['id']=='paper:https://openalex.org/W4402754006'
   assert profile['identity']['same_name_other_ids']==1
   assert r.author_profile(yi,bid,page=2,page_size=1)['papers']['items']==[]
   counts=r.run(lambda tx:{x['kind']:x['n'] for x in tx.run('MATCH (:CVEntity {batch_id:$b})-[r:CV_LINK]->() RETURN r.kind AS kind,count(r) AS n',b=bid)})
   assert counts=={'has_author':789,'affiliated_with':792,'published_in':150,'mentions_topic':17,'mentions_method':238,'mentions_task':124,'mentions_dataset':75}
  author=next(i['content']['key'] for p in d['papers'] for i in p['entities'] if i['content']['kind']=='author')
  assert r.author_profile(author,bid)['papers']['total']>=1
  changed=copy.deepcopy(d);removed=changed['papers'][0]['relations'].pop();seal(changed)
  new=r.ingest_effective(changed)['id'];r.publish(new,bid)
  assert r.batch(new)['relation_count']==d['counts']['relations']-1
  assert r.batch(bid)['relation_count']==d['counts']['relations']
  assert r.ingest_effective(d)['replay'];r.publish(bid,new)
  assert r.batch(bid)['relation_count']==d['counts']['relations']
  with TestClient(create_app(r,admin_token='test-only')) as c:
   assert c.get('/api/research/statistics',params={'batch_id':bid}).json()['paper_count']==len(d['papers'])
   assert c.post('/api/admin/graph/effective',json=d).status_code==401
  # Distinct per-paper venue display names survive projection and query.
  names=copy.deepcopy(d)
  if len(names['papers'])>1:
   venue=next(i for i in names['papers'][0]['entities'] if i['content']['kind']=='venue');venue['content']['name']='Paper-local display'
   venue['provenance']['review_state']='human_corrected';seal(names)
   nid=r.ingest_effective(names)['id'];r.publish(nid,bid)
   detail=r.detail(paper,nid)
   assert any(n['name']=='Paper-local display' for n in detail['related'])
   assert any(n['name']=='Paper-local display' for n in r.graph(paper,1,nid)['nodes'])
  report={'batch_id':bid,'counts':d['counts'],'unique_graph_entities':out['entity_count'],'checks':['import','counts','automatic_state','evidence','search','profile','statistics','idempotence','remove','restore','history','local_names']}
  target=os.getenv('EFFECTIVE_REPORT')
  if target:Path(target).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 finally:r.close()


def test_unicode_codepoint_offsets_and_whitespace_preserved():
 d=sample();p=d['papers'][0];raw=p['input'];raw['title']='😀 方法 '
 from src.graph_query.effective import fingerprint
 p['origin']['input_fingerprint']=fingerprint(raw)
 e=dict(paper_id=raw['openalex_id'],dataset_id=raw['dataset_id'],source_url=raw['source_url'],input_fingerprint=p['origin']['input_fingerprint'],field='title',quote='方法 ',start=2,end=5,path=[])
 for group in ('entities','relations'):
  for item in p[group]:item['evidence']=[copy.deepcopy(e)]
 seal(d);validate_effective(d)
 nodes,_=project(d)
 assert any(json.loads(n['contexts_json'])[0]['evidence'][0]['quote']=='方法 ' for n in nodes)
 e=p['entities'][0]['evidence'][0];e['start']=3;seal(d)
 with pytest.raises(ValueError):validate_effective(d)
