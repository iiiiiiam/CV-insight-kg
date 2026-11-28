import assert from 'node:assert/strict'
import test from 'node:test'
import {feedbackOwner,readReceipts,saveReceipt,feedbackDisplayStatus,refreshReceipts} from '../src/services/feedback-receipts.ts'
import {getFeedbackStatus,withdrawFeedback} from '../src/services/knowledge-feedback.ts'
import type {LocalStoragePort} from '../src/services/personal-knowledge.ts'
function memory():LocalStoragePort{
  const values=new Map<string,string>()
  return {getItem:key=>values.get(key)??null,setItem:(key,value)=>{values.set(key,value)},removeItem:key=>{values.delete(key)}}
}
test('feedback ownership persists in the same browser and differs between browsers',()=>{
  const browser=memory(),token=feedbackOwner(browser)
  assert.match(token,/^[0-9a-f]{64}$/)
  assert.equal(feedbackOwner(browser),token)
  assert.notEqual(feedbackOwner(memory()),token)
  const accountToken='b'.repeat(64)
  assert.equal(feedbackOwner(memory(),accountToken),accountToken)
})
test('receipts are scoped by paper and withdrawal updates status without duplicating the receipt',()=>{
  const browser=memory(),receipt={id:'r1',message:'test',status:'open' as const,created_at:'now'}
  saveReceipt(browser,'W1',receipt)
  assert.deepEqual(readReceipts(browser,'W2'),[])
  saveReceipt(browser,'W1',{...receipt,status:'withdrawn'})
  assert.deepEqual(readReceipts(browser,'W1'),[{...receipt,status:'withdrawn'}])
})
test('withdrawal sends proof in POST body, while status lookup never sends proof',async()=>{
  const previous=globalThis.fetch,calls:Array<{url:string;init?:RequestInit}>=[]
  globalThis.fetch=async(input,init)=>{calls.push({url:String(input),init});return Response.json({id:'r1',status:'withdrawn'})}
  try{
    const token='a'.repeat(64)
    await withdrawFeedback('r1',token);await getFeedbackStatus('r1')
    assert.equal(calls[0]!.url,'/api/knowledge/feedback/r1/withdraw')
    assert.equal(calls[0]!.init?.method,'POST')
    assert.deepEqual(JSON.parse(String(calls[0]!.init?.body)),{owner_token:token})
    assert.equal(calls[0]!.url.includes(token),false)
    assert.equal(calls[1]!.url,'/api/knowledge/feedback/r1')
    assert.equal(calls[1]!.init?.body,undefined)
  }finally{globalThis.fetch=previous}
})
test('cloud reply cache updates without duplicating receipt or losing original message',()=>{
  const storage=memory(),receipt={id:'local-1',message:'original',status:'open' as const,created_at:'now'}
  saveReceipt(storage,'W1',receipt)
  saveReceipt(storage,'W1',{...receipt,cloud:{delivery:'sent',feedback:{id:'cloud-1',status:'resolved',processing_note:'团队回复',state_revision:1,created_at:'now',updated_at:'later'}}})
  const saved=readReceipts(storage,'W1')
  assert.equal(saved.length,1)
  assert.equal(saved[0]!.message,'original')
  assert.equal(saved[0]!.status,'open')
  assert.equal(saved[0]!.cloud!.feedback!.processing_note,'团队回复')
  assert.equal(feedbackDisplayStatus(saved[0]!), 'resolved')
  assert.equal(feedbackDisplayStatus({...receipt,cloud:{delivery:'pending',feedback:null}}),'open')
})

test('one failed status preserves its reply and does not discard other refreshed receipts',async()=>{
 const items=[{id:'old',message:'old record',status:'open' as const,created_at:'now',cloud:{delivery:'sent' as const,feedback:{id:'cloud-old',status:'resolved' as const,processing_note:'saved reply',state_revision:1,created_at:'now',updated_at:'now'}}},
 {id:'new',message:'new record',status:'open' as const,created_at:'now'}]
 const result=await refreshReceipts(items,async id=>{if(id==='old')throw new Error('record unavailable');return {status:'dismissed' as const}})
 assert.equal(result.length,2)
 assert.equal(result[0]!.cloud!.feedback!.processing_note,'saved reply')
 assert.equal(result[0]!.refresh_error,'record unavailable')
 assert.equal(result[1]!.status,'dismissed')
 assert.equal(result[1]!.refresh_error,'')
})

test('missing withdrawn history remains visible without reporting an active submission error',async()=>{
 const record={id:'withdrawn-history',message:'old',status:'withdrawn' as const,created_at:'old'}
 const error=Object.assign(new Error('未找到反馈'),{status:404})
 const result=await refreshReceipts([record],async()=>{throw error})
 assert.equal(result[0]!.archived,true)
 assert.equal(result[0]!.refresh_error,'')
 assert.equal(result[0]!.status,'withdrawn')
})


test('unlinked history preserves cached replies and can reconnect on a later refresh',async()=>{
 const record={id:'old-install',message:'original',status:'open' as const,created_at:'old',cloud:{delivery:'sent' as const,feedback:{id:'cloud',status:'resolved' as const,processing_note:'saved reply',state_revision:1,created_at:'old',updated_at:'old'}}}
 const missing=Object.assign(new Error('未找到反馈'),{status:404})
 const history=await refreshReceipts([record],async()=>{throw missing})
 assert.equal(history[0]!.archived,true)
 assert.equal(history[0]!.refresh_error,'')
 assert.equal(history[0]!.cloud!.feedback!.processing_note,'saved reply')
 const restored=await refreshReceipts(history,async()=>({status:'resolved'}))
 assert.equal(restored[0]!.archived,false)
 const denied=await refreshReceipts([record],async()=>{throw Object.assign(new Error('请重新登录'),{status:401})})
 assert.equal(denied[0]!.archived,false)
 assert.equal(denied[0]!.refresh_error,'请重新登录')
})
