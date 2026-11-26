import assert from 'node:assert/strict'
import test from 'node:test'
import {auth} from '../src/stores/auth.ts'
import {createReport,getHandoffSync,getPipeline,retryTask} from '../src/services/workflows.ts'

test('automatic handoff reads status; only report creation and explicit retry issue writes',async()=>{
 const original=globalThis.fetch,calls:Array<{url:string;init?:RequestInit}>=[]
 auth.session={authenticated:true,username:'admin',display_name:'管理员',role:'admin',csrf_token:'fixture',expires_at:'2026-12-01T00:00:00Z'}
 globalThis.fetch=async(input,init)=>{calls.push({url:String(input),init});return Response.json({status:'synchronized',summary:{matched:[]}})}
 try{
  await getHandoffSync()
  await createReport({request_key:'report-1',title:'报告',sections:[]})
  await retryTask('handoffs','task-1')
  assert.deepEqual(calls.map(c=>c.url),['/api/admin/handoff-sync','/api/admin/reports','/api/admin/handoffs/task-1/retry'])
  assert.equal(calls[0]!.init?.method,undefined)
  for(const c of calls.slice(1)){assert.equal(c.init?.method,'POST');assert.equal(new Headers(c.init?.headers).get('X-CSRF-Token'),'fixture')}
 }finally{globalThis.fetch=original;auth.session=null}
})

test('automatic handoff pipeline preserves independent A B C stages',async()=>{
 const original=globalThis.fetch
 globalThis.fetch=async()=>Response.json({task_id:'task-1',stages:{A:{status:'succeeded'},B:{status:'processing'},C:{status:'waiting'}}})
 try{const r=await getPipeline('task-1');assert.equal(r.stages.A.status,'succeeded');assert.equal(r.stages.B.status,'processing');assert.equal(r.stages.C.status,'waiting')}
 finally{globalThis.fetch=original}
})
