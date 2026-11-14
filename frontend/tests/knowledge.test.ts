import assert from 'node:assert/strict'
import test from 'node:test'
import {candidateLabel,candidateRows,getKnowledgeDetail,submitKnowledgeReview,fetchKnowledgeDownload,getConfirmedKnowledge} from '../src/services/knowledge.ts'
import type {Candidate,EntityContent,Evidence,KnowledgeDetail,ReviewItem} from '../src/services/knowledge.ts'

// Test-only model of separate extraction/review payloads. Never imported by the UI.
const paper:EntityContent={key:'test:paper',kind:'paper',name:'Program test paper',source_id:null}
const task:EntityContent={key:'test:task',kind:'task',name:'Detection',source_id:null}
const proof:Evidence={paper_id:'test:paper',dataset_id:'test-only',source_url:'https://example.org/paper',
  input_fingerprint:'test-only',field:'title',quote:'Program',start:0,end:7,path:[]}
const entities:Candidate[]=[{candidate_id:'p',entity:paper,status:'pending',evidence:[proof]},
  {candidate_id:'t',entity:task,status:'pending',evidence:[proof]}]
const relations:Candidate[]=[{candidate_id:'r',source:paper.key,target:task.key,kind:'mentions_task',status:'pending',evidence:[proof]}]
const items:ReviewItem[]=[{candidate_id:'p',content:paper,evidence:[proof],status:'confirmed'},
  {candidate_id:'t',content:{...task,name:'程序测试纠正名'},evidence:[{...proof,field:'abstract'}],status:'confirmed'},
  {candidate_id:'r',content:{source:paper.key,target:task.key,kind:'mentions_task'},evidence:[proof],status:'rejected'}]
function detail():KnowledgeDetail{
  return {result:{entities,relations},review:{items,history:[]}} as unknown as KnowledgeDetail
}

test('current review shows corrected name, evidence and status without modifying extraction',()=>{
  const input=detail(),before=JSON.stringify(input.result)
  const current=candidateRows(input,'entities','reviewed')
  assert.equal(current[1]!.entity!.name,'程序测试纠正名')
  assert.equal(current[1]!.status,'confirmed')
  assert.deepEqual(current[1]!.changed_fields,['名称','证据'])
  assert.equal(current[1]!.evidence[0]!.field,'abstract')
  assert.equal(JSON.stringify(input.result),before)
})
test('original view keeps pending state and original evidence even when review is confirmed',()=>{
  const rows=candidateRows(detail(),'entities','original')
  assert.equal(rows[1]!.entity!.name,'Detection')
  assert.equal(rows[1]!.status,'pending')
  assert.equal(rows[1]!.evidence[0]!.field,'title')
  assert.deepEqual(rows[1]!.changed_fields,[])
  assert.equal(candidateRows(detail(),'entities','original','confirmed').length,0)
})
test('entity/relation and three-state filters use the review items',()=>{
  assert.equal(candidateRows(detail(),'entities','reviewed','confirmed').length,2)
  assert.equal(candidateRows(detail(),'entities','reviewed','rejected').length,0)
  const relations=candidateRows(detail(),'relations','reviewed','rejected')
  assert.equal(relations.length,1)
  assert.equal(relations[0]!.source,paper.key)
  assert.equal(relations[0]!.status,'rejected')
})
test('relation labels resolve current names separately from original names',()=>{
  const input=detail()
  assert.match(candidateLabel(input,candidateRows(input,'relations','reviewed')[0]!,'reviewed'),/程序测试纠正名/)
  assert.match(candidateLabel(input,candidateRows(input,'relations','original')[0]!,'original'),/Detection/)
})
test('detail requests bind the overview revision, and a stale snapshot error is surfaced',async()=>{
  const original=globalThis.fetch,calls:string[]=[]
  globalThis.fetch=async(input)=>{
    calls.push(String(input))
    return new Response(JSON.stringify({error:{code:'KNOWLEDGE_SNAPSHOT_CHANGED',message:'审核存档已变化，请刷新'}}),{status:409})
  }
  try{
    await assert.rejects(getKnowledgeDetail('https://openalex.org/W1',undefined,'a'.repeat(64)),/请刷新/)
    const query=new URL(calls[0]!,'http://localhost').searchParams
    assert.equal(query.get('paper_id'),'https://openalex.org/W1')
    assert.equal(query.get('snapshot_revision'),'a'.repeat(64))
  }finally{globalThis.fetch=original}
})

test('review writes carry CSRF and the viewed revision, without a browser-supplied reviewer',async()=>{
  const original=globalThis.fetch
  globalThis.fetch=async(input,init)=>{
    assert.equal(String(input),'/api/admin/knowledge/reviews')
    assert.equal(init?.method,'POST')
    assert.equal(init?.credentials,'same-origin')
    assert.equal(new Headers(init?.headers).get('X-CSRF-Token'),'program-test-csrf')
    const payload=JSON.parse(String(init?.body))
    assert.equal(payload.snapshot_revision,'a'.repeat(64))
    assert.equal(payload.action,'confirm')
    assert.equal('reviewer' in payload,false)
    assert.equal('evidence' in payload,false)
    return new Response(JSON.stringify({saved:true,affected_candidate_ids:['candidate']}))
  }
  try{assert.equal((await submitKnowledgeReview({paper_id:'test',candidate_id:'candidate',action:'confirm',reason:'Program test',snapshot_revision:'a'.repeat(64)},'program-test-csrf')).saved,true)}
  finally{globalThis.fetch=original}
})

test('business download binds current revision and rejects stale/error bodies as files',async()=>{
  const original=globalThis.fetch
  let fail=false
  globalThis.fetch=async(input,init)=>{
    const url=new URL(String(input),'http://localhost')
    assert.equal(url.pathname,'/api/admin/knowledge/exports/bundle.zip')
    assert.equal(url.searchParams.get('snapshot_revision'),'b'.repeat(64))
    assert.equal(init?.credentials,'same-origin')
    return fail?new Response(JSON.stringify({error:{message:'已变化，请重新读取'}}),{status:409}):new Response(new Uint8Array([80,75,3,4]),{headers:{'Content-Type':'application/zip'}})
  }
  try{
    assert.equal((await fetchKnowledgeDownload('bundle.zip','b'.repeat(64))).size,4)
    fail=true
    await assert.rejects(fetchKnowledgeDownload('bundle.zip','b'.repeat(64)),/重新读取/)
  }finally{globalThis.fetch=original}
})

test('paper detail requests the public confirmed-only projection',async()=>{
  const original=globalThis.fetch
  globalThis.fetch=async(input)=>{
    const url=new URL(String(input),'http://localhost')
    assert.equal(url.pathname,'/api/knowledge/confirmed')
    assert.equal(url.searchParams.get('paper_id'),'https://openalex.org/W1')
    return new Response(JSON.stringify({supported:true,entities:[],relations:[],notice:'暂无已确认内容'}))
  }
  try{assert.deepEqual((await getConfirmedKnowledge('https://openalex.org/W1')).entities,[])}
  finally{globalThis.fetch=original}
})
