import json,os
from pathlib import Path
import pytest
from test_neo4j import repo
from src.graph_query.effective_source import FileEffectiveSource
from src.graph_query.api import create_app
from fastapi.testclient import TestClient

pytestmark=pytest.mark.skipif(not os.getenv('GRAPH_TEST_URI'),reason='isolated Neo4j required')

def test_real_hop_identity_expansion(repo):
 source=os.getenv('EFFECTIVE_TEST_FILE',Path(__file__).resolve().parents[2]/'sample_data/graph/effective-minimal.json')
 doc=FileEffectiveSource(source).load();b=repo.ingest_effective(doc)['id'];repo.publish(b,repo.batch(b)['active_batch_id'])
 seed='paper:https://openalex.org/W4402754006' if len(doc['papers'])==150 else next(i['content']['key'] for i in doc['papers'][0]['entities'] if i['content']['kind']=='paper')
 one=repo.graph(seed,1,b,60);two=repo.graph(seed,2,b,60);again=repo.graph(seed,2,b,60)
 n1={n['id'] for n in one['nodes']};n2={n['id'] for n in two['nodes']};e1={e['id'] for e in one['edges']};e2={e['id'] for e in two['edges']}
 assert not one['truncated'];assert n1<=n2 and e1<=e2;assert n2-n1 and e2-e1
 assert e2=={e['id'] for e in again['edges']}
 assert all(e['source'] in n2 and e['target'] in n2 for e in two['edges'])
 # Reproduce the old unordered mixed-depth LIMIT in the same immutable snapshot.
 def old(tx):
  rows=list(tx.run('MATCH path=(s:CVEntity {batch_id:$b,id:$seed})-[:CV_LINK*1..2]-(n:CVEntity) WHERE all(v IN nodes(path) WHERE v.batch_id=$b) RETURN path LIMIT 61',b=b,seed=seed))
  return {'nodes':sorted({n['id'] for row in rows[:60] for n in row['path'].nodes}), 'edges':sorted({e['id'] for row in rows[:60] for e in row['path'].relationships}), 'truncated':len(rows)>60}
 before=repo.run(old)
 report={'seed':seed,'batch_id':b,'limit_paths':60,'one':{'nodes':sorted(n1),'edges':sorted(e1),'truncated':one['truncated']},'two':{'nodes':sorted(n2),'edges':sorted(e2),'truncated':two['truncated']},'added_node_ids':sorted(n2-n1),'added_edge_ids':sorted(e2-e1),'old_unordered_query':before,'backend_policy':two['traversal_policy'],'environment':'isolated exact effective snapshot; current 8002 unavailable'}
 with TestClient(create_app(repo,admin_token='test-only')) as c:
  for h,g in [(1,one),(2,two)]:
   d=c.get('/api/research/graph',params={'seed':seed,'batch_id':b,'hops':h,'limit':60}).json();assert {n['id'] for n in d['nodes']}=={n['id'] for n in g['nodes']}
  assert c.get('/research').status_code==c.get('/research/analytics').status_code==200
  assert all('/assets/c-graph-view.js' in c.get(page).text for page in ['/research','/research/analytics'])
  assert c.get('/assets/c-graph-view.js').status_code==200
 path=os.getenv('HOPS_REPORT')
 if path:Path(path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
