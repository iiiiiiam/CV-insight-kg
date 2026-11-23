"""C Week4 boundaries and isolated Neo4j checks; fixtures are never production data."""
import copy
import json
import os
import secrets
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable

from src.graph_query.api import create_app
from src.graph_query.models import BatchInput
from src.graph_query.repository import GraphError
from test_neo4j import repo, batch
from src.graph_query.annual import annual_axis


@pytest.mark.parametrize('rows,start,end,counts,missing',[
    ([],None,None,[],0),
    ([],2022,2024,[0,0,0],0),
    ([{'year':2024,'paper_count':3}],None,None,[3],0),
    ([{'year':2022,'paper_count':2},{'year':2024,'paper_count':1}],None,None,[2,0,1],0),
    ([{'year':None,'paper_count':2},{'year':2024,'paper_count':1}],2023,2024,[0,1],2),
])
def test_internal_year_axis_without_business_series(rows,start,end,counts,missing):
    axis=annual_axis(rows,start,end)
    assert [p['paper_count'] for p in axis['points']]==counts
    assert axis['missing_year_papers']==missing and axis['complete_year_metadata']==(missing==0)


@pytest.mark.parametrize('rows,start,end',[
    ([],2025,2024),([],1800,2024),([{'year':2024,'paper_count':-1}],None,None),
    ([{'year':2024,'paper_count':1},{'year':2024,'paper_count':2}],None,None),
])
def test_internal_year_axis_rejects_ambiguous_aggregation(rows,start,end):
    with pytest.raises(ValueError):annual_axis(rows,start,end)


class Boundary:
    def initialize(self): pass
    def publication_status(self, *args): return {"active_batch_id":None, "items":[]}
    def partners(self, *args): return {"args":args}
    def report_statistics(self, *args): return {"args":args}
    def publish(self, *args, **kwargs): raise ServiceUnavailable("test-only injected outage")
    def ingest_effective(self, body): raise ValueError("test-only invalid export")


def test_unexpected_publish_error_has_safe_diagnostic():
    class Failed(Boundary):
        def publish(self,*args,**kwargs):raise RuntimeError('test-only private diagnostic')
    token=secrets.token_urlsafe(32)
    with TestClient(create_app(Failed(),admin_token=token),raise_server_exceptions=False) as client:
        response=client.post('/api/admin/batches/x/publish',json={'expected_active_batch_id':None},headers={'Authorization':'Bearer '+token})
        assert response.status_code==500 and response.json()['error']['code']=='GRAPH_INTERNAL_ERROR'
        assert response.json()['error']['stage']=='publish' and 'private diagnostic' not in response.text


def test_week4_api_boundaries():
    token=secrets.token_urlsafe(32)
    with TestClient(create_app(Boundary(),admin_token=token)) as client:
        headers={"Authorization":"Bearer "+token}
        assert client.get('/api/admin/graph/publication-status').status_code==401
        assert client.get('/api/admin/graph/publication-status',headers=headers).json()['items']==[]
        assert client.get('/api/research/report-statistics').status_code==422
        assert client.get('/api/research/report-statistics?batch_id=x&expected_revision=no').status_code==422
        result=client.get('/api/research/coauthors',params={'anchor_id':'author:stable','batch_id':'x','page_size':1}).json()
        assert result['args'][:3]==['author:stable','x','author']
        assert client.get('/api/research/coauthors?anchor_id=x&batch_id=x&page_size=101').status_code==422
        response=client.post('/api/admin/graph/effective',json={},headers=headers)
        assert response.status_code==422 and response.json()['error']['stage']=='validate'
        response=client.post('/api/admin/batches/x/publish',json={'expected_active_batch_id':None},headers=headers)
        assert response.status_code==503
        assert response.json()['error']['publication_outcome_unknown'] is True
        assert 'test-only' not in response.text
        assert client.post('/api/admin/batches/x/publish',json={'expected_active_batch_id':None,'expected_publish_generation':-1},headers=headers).status_code==422


needs_db=pytest.mark.skipif(not os.getenv('GRAPH_TEST_URI'),reason='isolated real Neo4j required')


@needs_db
def test_coauthors_identity_pages_filters_and_institution_evidence(repo,batch):
    d=batch.model_dump(mode='json')
    papers=[n['id'] for n in d['entities'] if n['kind']=='paper']
    p1,p2=papers[:2]
    first=[r for r in d['relations'] if r['source']==p1 and r['kind']=='has_author']
    second=[r for r in d['relations'] if r['source']==p2 and r['kind']=='has_author']
    a,b=first[0]['target'],first[1]['target']
    # Deliberately equal display names, distinct stable IDs, plus shared papers.
    for n in d['entities']:
        if n['id'] in (b,second[0]['target']):n['name']='Same Name'
    for target in (a,b):
        relation=copy.deepcopy(second[0]);relation['target']=target;d['relations'].append(relation)
    for ident in ('institution:I','institution:J','institution:K'):
        d['entities'].append(dict(id=ident,kind='institution',name=ident,updated_at=d['entities'][0]['updated_at']))
    for author,institution,evidence in ((a,'institution:I',first[0]['evidence']),
                                       (b,'institution:J',first[1]['evidence']),
                                       (a,'institution:K',second[0]['evidence'])):
        d['relations'].append(dict(source=author,target=institution,kind='affiliated_with',status='confirmed',evidence=evidence))
    batch=BatchInput.model_validate(d)
    repo.ingest(batch);repo.publish(batch.batch_id,repo.batch(batch.batch_id)['active_batch_id'],True)
    out=repo.partners(a,batch.batch_id,page_size=1,paper_limit=1)
    assert out['anchor']['paper_count']==2 and out['items'][0]['id']==b
    assert out['items'][0]['paper_count']==2 and out['items'][0]['shared_papers_truncated']
    ids=[]
    for page in range(1,out['total']+1):
        ids += [x['id'] for x in repo.partners(a,batch.batch_id,page=page,page_size=1)['items']]
    assert len(ids)==len(set(ids))==out['total']
    assert b in ids and second[0]['target'] in ids
    assert repo.partners(a,batch.batch_id)==repo.partners(a,batch.batch_id)
    assert repo.partners(a,batch.batch_id,filters={'q':'no matching paper'})['total']==0
    with pytest.raises(GraphError):repo.partners('missing-stable-id',batch.batch_id)
    report=repo.report_statistics(batch.batch_id,author_id=a,institution_id='institution:I')
    institutions={x['id']:x['paper_count'] for x in report['data']['institutions']['items']}
    assert institutions=={'institution:I':1,'institution:J':1,'institution:K':1}
    assert [x['id'] for x in report['data']['institution_collaborations']['items']]==['institution:J']
    assert report['data']['statistics']==repo.statistics({},batch.batch_id)
    assert report['data']['trends']['series'] is None


@needs_db
def test_publish_after_pointer_write_failure_rolls_back(repo,batch,monkeypatch):
    repo.ingest(batch);before=repo.publication_status()
    original=repo.run
    def injected(operation,*,write=False):
        def wrapped(tx):
            class Fault:
                def run(self,query,*args,**kwargs):
                    result=tx.run(query,*args,**kwargs)
                    if "SET r.active_batch_id=$id" in query:
                        result.consume()
                        raise RuntimeError('test-only failure before transaction commit')
                    return result
            return operation(Fault())
        return original(wrapped,write=write)
    with monkeypatch.context() as patch:
        patch.setattr(repo,'run',injected)
        with pytest.raises(RuntimeError):repo.publish(batch.batch_id,before['active_batch_id'],True)
    after=repo.publication_status()
    assert (after['active_batch_id'],after['publish_generation'])==(before['active_batch_id'],before['publish_generation'])
    assert repo.batch(batch.batch_id)['status']=='ready'
    repo.publish(batch.batch_id,before['active_batch_id'],True,after['publish_generation'])
    assert repo.papers({})['batch_id']==batch.batch_id


@needs_db
def test_publish_generation_aba_and_repeat(repo,batch):
    repo.ingest(batch);start=repo.publication_status()
    first=repo.publish(batch.batch_id,start['active_batch_id'],True,start['publish_generation'])
    replay=repo.publish(batch.batch_id,batch.batch_id,True,first['publish_generation'])
    assert replay['unchanged'] and replay['publish_generation']==first['publish_generation']
    d=batch.model_dump(mode='json');d['batch_id']+='-other';other=BatchInput.model_validate(d);repo.ingest(other)
    repo.publish(other.batch_id,batch.batch_id,True)
    repo.publish(batch.batch_id,other.batch_id,True)
    with pytest.raises(GraphError) as exc:repo.publish(other.batch_id,batch.batch_id,True,first['publish_generation'])
    assert exc.value.code=='ACTIVE_BATCH_CHANGED'
    assert repo.publication_status()['active_batch_id']==batch.batch_id


@needs_db
def test_many_author_paper_is_bounded(repo,batch):
    d=batch.model_dump(mode='json');p=next(n['id'] for n in d['entities'] if n['kind']=='paper')
    original=next(r for r in d['relations'] if r['source']==p and r['kind']=='has_author')
    for i in range(250):
        ident='author:test-only-many-'+str(i)
        d['entities'].append(dict(id=ident,kind='author',name='Test only author '+str(i),updated_at=d['entities'][0]['updated_at']))
        edge=copy.deepcopy(original);edge['target']=ident;d['relations'].append(edge)
    b=BatchInput.model_validate(d);repo.ingest(b);repo.publish(b.batch_id,repo.batch(b.batch_id)['active_batch_id'],True)
    out=repo.partners(original['target'],b.batch_id,page_size=5,paper_limit=1)
    assert out['total']==256 and len(out['items'])==5 and out['truncated']
    assert all(i['paper_count']==1 and len(i['shared_papers'])==1 for i in out['items'])


@needs_db
def test_effective_mid_import_and_quality_failure_recover(repo,monkeypatch):
    from test_effective import sample,seal
    doc=sample();doc['papers'][0]['entities'][0]['candidate_id']+='-week4-failure-test'
    seal(doc);bid='effective-'+doc['revision'];before=repo.publication_status();original=repo.run
    def injected(operation,*,write=False):
        def wrapped(tx):
            class Fault:
                def run(self,query,*args,**kwargs):
                    if query.startswith('UNWIND $edges'):raise RuntimeError('test-only effective import failure')
                    return tx.run(query,*args,**kwargs)
            return operation(Fault())
        return original(wrapped,write=write)
    with monkeypatch.context() as patch:
        patch.setattr(repo,'run',injected)
        with pytest.raises(RuntimeError):repo.ingest_effective(doc)
    with pytest.raises(GraphError):repo.batch(bid)
    count=repo.run(lambda tx:tx.run('MATCH (n:CVEntity {batch_id:$batch}) RETURN count(n) AS n',batch=bid).single()['n'])
    assert count==0 and repo.publication_status()['active_batch_id']==before['active_batch_id']
    repo.ingest_effective(doc)
    with monkeypatch.context() as patch:
        def quality_failure(*args):raise GraphError(409,'QUALITY_CHECK_FAILED','test-only evidence fault')
        patch.setattr(repo,'_check_effective',quality_failure)
        with pytest.raises(GraphError):repo.publish(bid,before['active_batch_id'])
    assert repo.publication_status()['active_batch_id']==before['active_batch_id']
    repo.publish(bid,before['active_batch_id'])
    assert repo.papers({})['batch_id']==bid


@needs_db
@pytest.mark.skipif(not os.getenv('WEEK4_EXPORTS'),reason='actual Week4 A→B exports required')
def test_week4_actual_a_b_report_lifecycle(repo,monkeypatch):
    root=Path(os.environ['WEEK4_EXPORTS'])
    documents=[json.loads((root/(name+'-effective.json')).read_text(encoding='utf-8')) for name in ('first','merged','withdrawn','empty')]
    assert [d['counts']['papers'] for d in documents]==[20,30,20,0]
    records=[];ids=[]
    for doc in documents:
        bid=repo.ingest_effective(doc)['id'];assert repo.ingest_effective(doc)['replay']
        status=repo.publication_status()
        repo.publish(bid,status['active_batch_id'],expected_generation=status['publish_generation'])
        assert repo.publish(bid,bid)['unchanged']
        ids.append(bid)
        # Verify every ranked author and all shared witnesses against actual B has_author edges.
        authors=defaultdict(set);titles={}
        for paper in doc['papers']:
            pid='paper:'+paper['input']['openalex_id'];titles[pid]=paper['input']['title']
            for rel in paper['relations']:
                if rel['content']['kind']=='has_author':authors[rel['content']['target']].add(pid)
        anchor=max(authors,key=lambda a:(len(authors[a]),a)) if authors else None
        calls=[];run=repo.run
        with monkeypatch.context() as patch:
            def counted(op,**kw):calls.append(1);return run(op,**kw)
            patch.setattr(repo,'run',counted)
            report=repo.report_statistics(bid,doc['revision'],limit=100,author_id=anchor)
        assert len(calls)==1  # Fixed immutable snapshot, no per-section re-resolve.
        data=report['data'];assert report['revision']==doc['revision']
        if os.getenv('WEEK4_A_REFERENCE'):
            # Execute A's unchanged pure guard, without importing its DB/task stack
            # or writing bytecode/caches into the read-only reference directory.
            import ast
            source=Path(os.environ['WEEK4_A_REFERENCE'])/'app/report_bundle.py'
            tree=ast.parse(source.read_text(encoding='utf-8'))
            guard=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='validate_sections')
            namespace={}
            exec(compile(ast.Module(body=[guard],type_ignores=[]),str(source),'exec'),namespace)
            frozen={'papers':[{'paper_id':p['input']['openalex_id']} for p in doc['papers']]}
            namespace['validate_sections'](frozen,[report])
            invalid=copy.deepcopy(report);invalid['data']['statistics']['paper_count']+=1
            with pytest.raises(ValueError):namespace['validate_sections'](frozen,[invalid])
        assert set(report['paper_ids'])=={p['input']['openalex_id'] for p in doc['papers']}
        assert data['statistics']['paper_count']==len(doc['papers'])
        assert data['statistics']==repo.statistics({},bid,100)
        assert sum(y['paper_count'] for y in data['years'])==len(doc['papers'])
        for a in data['authors']['items']:assert a['paper_count']==len(authors[a['id']])
        assert data['authors']['source_identified_total']+data['authors']['without_source_id_total']==len(authors)
        for kind in ('topic','method','task','dataset'):
            expected=defaultdict(set)
            for paper in doc['papers']:
                for r in paper['relations']:
                    if r['content']['kind']=='mentions_'+kind:expected[r['content']['target']].add(paper['input']['openalex_id'])
            actual={i['id']:i['paper_count'] for i in data['distributions'][kind]['items']}
            assert actual=={k:len(v) for k,v in expected.items()}
        if anchor:
            expected={a:len(ps & authors[anchor]) for a,ps in authors.items() if a!=anchor and ps & authors[anchor]}
            actual=data['coauthors'];assert actual['total']==len(expected)
            for item in actual['items']:
                assert item['paper_count']==expected[item['id']]
                assert {p['id'] for p in item['shared_papers']} <= authors[anchor]&authors[item['id']]
                assert all(p['title']==titles[p['id']] and p['source_url'] for p in item['shared_papers'])
        records.append(dict(batch_id=bid,revision=doc['revision'],papers=len(doc['papers']),
                            authors=data['authors']['total'],institutions=data['institutions']['total'],
                            authors_without_source_id=data['authors']['without_source_id_total'],
                            anchor=anchor,coauthors=data['coauthors'].get('total',0)))
    for bid,n in zip(ids,[20,30,20,0]):assert repo.report_statistics(bid)['data']['statistics']['paper_count']==n
    with pytest.raises(GraphError) as exc:repo.report_statistics(ids[0],'0'*64)
    assert exc.value.code=='REPORT_REVISION_MISMATCH'
    # Replayed old notifications cannot publish with the pre-empty pointer/generation.
    status=repo.publication_status()
    with pytest.raises(GraphError):repo.publish(ids[0],ids[1])
    assert repo.publication_status()['active_batch_id']==ids[-1]
    token=secrets.token_urlsafe(32)
    with TestClient(create_app(repo,admin_token=token)) as client:
        headers={'Authorization':'Bearer '+token}
        for mutation in ('format','revision','count'):
            bad=copy.deepcopy(documents[0])
            if mutation=='format':bad['format_version']='wrong'
            elif mutation=='revision':bad['revision']='0'*64
            else:bad['counts']['papers']+=1
            assert client.post('/api/admin/graph/effective',json=bad,headers=headers).status_code==422
            assert repo.papers({})['batch_id']==ids[-1]
        response=client.get('/api/research/report-statistics',params={'batch_id':ids[-1],'expected_revision':documents[-1]['revision']})
        assert response.status_code==200 and response.json()['paper_ids']==[]
        assert client.get('/api/admin/graph/publication-status',headers=headers).json()['active_batch_id']==ids[-1]
    assert repo.ingest_effective(documents[0])['replay']  # Recovery does not lose old input.
    target=os.getenv('WEEK4_REPORT')
    if target:Path(target).write_text(json.dumps(dict(mode='actual A files → read-only Week4 B code offline → C → isolated Neo4j; not live team integration',snapshots=records,checks=['20-30-20-0','history','distinct authors and shared papers','four knowledge distributions','report revision and paper scope','single read transaction','invalid snapshots retain active','out-of-order CAS rejected']),ensure_ascii=False,indent=2),encoding='utf-8')
