import assert from 'node:assert/strict'
import test from 'node:test'
import {getReading,itemName,sendFeedback,resolveFeedback,reopenFeedback,downloadEffectiveKnowledge} from '../src/services/knowledge-feedback.ts'
import type {ReadingKnowledge} from '../src/services/knowledge-feedback.ts'

test('automatic reading uses stable IDs and translates relation labels without status labels',()=>{
  const view={entities:[{candidate_id:'p',content:{key:'paper:1',name:'Paper',kind:'paper'},evidence:[]},
    {candidate_id:'d',content:{key:'dataset:1',name:'LVIS',kind:'dataset'},evidence:[]}],relations:[]} as unknown as ReadingKnowledge
  assert.equal(itemName({candidate_id:'r',content:{source:'paper:1',kind:'mentions_dataset',target:'dataset:1'},evidence:[]},view),'Paper → 提及数据集 → LVIS')
})

test('reading encodes source ID and feedback preserves the viewed revision without reviewer',async()=>{
  const previous=globalThis.fetch
  const calls:Array<{url:string;body:unknown}>=[]
  globalThis.fetch=async(input,init)=>{calls.push({url:String(input),body:init?.body?JSON.parse(String(init.body)):null});return Response.json({id:'test',status:'open',duplicate:false})}
  try{
    await getReading('https://openalex.org/W1')
    const body={paper_id:'https://openalex.org/W1',revision:'a'.repeat(64),message:'test',term:'RepVL-PAN'}
    await sendFeedback(body)
    assert.equal(new URL(calls[0]!.url,'http://test').searchParams.get('paper_id'),body.paper_id)
    assert.deepEqual(calls[1]!.body,body)
    assert.equal(calls[1]!.url,'/api/knowledge/feedback')
  }finally{globalThis.fetch=previous}
})

test('admin feedback handling carries session CSRF and queue revision',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async(input,init)=>{
    assert.equal(String(input),'/api/admin/knowledge/feedback/test-id')
    assert.equal(new Headers(init?.headers).get('X-CSRF-Token'),'test-csrf')
    assert.deepEqual(JSON.parse(String(init?.body)),{revision:7,action:'dismiss',reason:'test'})
    return Response.json({id:'test-id',status:'dismissed'})
  }
  try{await resolveFeedback('test-id',{revision:7,action:'dismiss',reason:'test'},'test-csrf')}
  finally{globalThis.fetch=previous}
})

test('admin undo uses authenticated POST with queue revision and no supplied reviewer',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async(input,init)=>{
    assert.equal(String(input),'/api/admin/knowledge/feedback/test-id/reopen')
    assert.equal(init?.method,'POST')
    assert.equal(new Headers(init?.headers).get('X-CSRF-Token'),'undo-csrf')
    assert.deepEqual(JSON.parse(String(init?.body)),{revision:8})
    return Response.json({id:'test-id',status:'open'})
  }
  try{assert.equal((await reopenFeedback('test-id',8,'undo-csrf')).status,'open')}
  finally{globalThis.fetch=previous}
})

test('effective export downloads a versioned JSON file with the admin session',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async(input,init)=>{
    assert.equal(String(input),'/api/admin/knowledge/effective-export')
    assert.equal(init?.credentials,'same-origin')
    return Response.json({format_version:'knowledge-effective/1.0'},{headers:{'X-Knowledge-Revision':'a'.repeat(64)}})
  }
  try{const result=await downloadEffectiveKnowledge();assert.equal(result.filename,'effective-aaaaaaaaaaaa.json');assert.equal(JSON.parse(await result.blob.text()).format_version,'knowledge-effective/1.0')}
  finally{globalThis.fetch=previous}
})
test('effective export surfaces auth failures instead of saving error JSON',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async()=>Response.json({detail:'请先登录'},{status:401})
  try{await assert.rejects(downloadEffectiveKnowledge(),/请先登录/)}finally{globalThis.fetch=previous}
})
test('effective export rejects a success body without a knowledge revision',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async()=>Response.json({unexpected:true})
  try{await assert.rejects(downloadEffectiveKnowledge(),/导出响应不完整/)}finally{globalThis.fetch=previous}
})
