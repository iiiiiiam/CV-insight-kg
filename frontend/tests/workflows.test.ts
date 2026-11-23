import assert from 'node:assert/strict'
import test from 'node:test'
import {auth} from '../src/stores/auth.ts'
import {createHandoff,createReport,getPipeline,getPublicationStatus} from '../src/services/workflows.ts'

const session={authenticated:true as const,username:'admin',display_name:'管理员',role:'admin' as const,
  csrf_token:'workflow-csrf',expires_at:'2026-12-01T00:00:00Z'}

test('workflow writes use the admin CSRF token and keep version-bound inputs',async()=>{
  const previous=globalThis.fetch,calls:Array<{url:string;init?:RequestInit}>=[]
  auth.session=session
  globalThis.fetch=async(input,init)=>{
    calls.push({url:String(input),init})
    return Response.json({id:'task-1',kind:String(input).includes('handoffs')?'handoff':'report',status:'queued',stage:'queued',progress:0,attempts:0,events:[]})
  }
  try{
    await createHandoff(7,'a'.repeat(64),'handoff-request')
    await createReport({request_key:'report-request',title:'集成报告',scope:{paper_ids:['https://openalex.org/W1']},sections:[]})
    assert.deepEqual(calls.map(call=>call.url),['/api/admin/handoffs','/api/admin/reports'])
    for(const call of calls){
      assert.equal(call.init?.method,'POST')
      assert.equal(new Headers(call.init?.headers).get('X-CSRF-Token'),'workflow-csrf')
    }
    assert.deepEqual(JSON.parse(String(calls[0]!.init?.body)),{
      batch_id:7,expected_revision:'a'.repeat(64),request_key:'handoff-request',acknowledge_switch:true,
    })
    assert.deepEqual(JSON.parse(String(calls[1]!.init?.body)).scope.paper_ids,['https://openalex.org/W1'])
  }finally{globalThis.fetch=previous;auth.session=null}
})

test('pipeline status keeps A B and C as separate stages',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async()=>Response.json({task_id:'task-1',stages:{
    A:{status:'succeeded',message:'A fixed'},B:{status:'processing',message:'B extracting'},C:{status:'waiting',message:'C pending'},
  }})
  try{
    const result=await getPipeline('task-1')
    assert.equal(result.stages.A.status,'succeeded')
    assert.equal(result.stages.B.status,'processing')
    assert.equal(result.stages.C.status,'waiting')
  }finally{globalThis.fetch=previous}
})

test('publication history is read through the D admin gateway',async()=>{
  const previous=globalThis.fetch
  globalThis.fetch=async input=>{
    const url=new URL(String(input),'http://test')
    assert.equal(url.pathname,'/api/admin/graph/publication-status')
    assert.equal(url.searchParams.get('page'),'2')
    assert.equal(url.searchParams.get('page_size'),'20')
    return Response.json({active_batch_id:'effective-current',active:{id:'effective-current',status:'published'},
      publish_generation:7,items:[{id:'effective-current',status:'published'}],total:1,page:2,page_size:20})
  }
  try{
    const result=await getPublicationStatus(2)
    assert.equal(result.publish_generation,7)
    assert.equal(result.items[0]?.id,result.active_batch_id)
  }finally{globalThis.fetch=previous}
})
