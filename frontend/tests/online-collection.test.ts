import assert from 'node:assert/strict'
import test from 'node:test'
import {auth} from '../src/stores/auth.ts'
import {collectOnline,getOnlineCollection} from '../src/services/online-collection.ts'

test('online collection submits a bounded explicit scope with the admin session',async()=>{
 const previous=globalThis.fetch,calls:Array<{url:string;init?:RequestInit}>=[]
 auth.session={authenticated:true,username:'admin',display_name:'管理员',role:'admin',csrf_token:'fixture',expires_at:'2026-12-01T00:00:00Z'}
 globalThis.fetch=async(input,init)=>{calls.push({url:String(input),init});return Response.json({id:12,status:'queued'})}
 try{
  await collectOnline({request_key:'online-1',venue:'CVPR',year:2025,count:20,keyword:'3D'})
  await getOnlineCollection(12)
  assert.deepEqual(calls.map(c=>c.url),['/api/admin/online-collections','/api/admin/online-collections/12'])
  assert.equal(calls[0]!.init?.method,'POST');assert.equal(new Headers(calls[0]!.init?.headers).get('X-CSRF-Token'),'fixture')
  assert.deepEqual(JSON.parse(String(calls[0]!.init?.body)),{request_key:'online-1',venue:'CVPR',year:2025,count:20,keyword:'3D'})
 }finally{globalThis.fetch=previous;auth.session=null}
})

test('online source failure is surfaced as an error, never as a successful import',async()=>{
 const previous=globalThis.fetch;globalThis.fetch=async()=>Response.json({detail:'在线来源暂不可用'},{status:503})
 try{await assert.rejects(()=>getOnlineCollection(12),/在线来源暂不可用/)}finally{globalThis.fetch=previous}
})
