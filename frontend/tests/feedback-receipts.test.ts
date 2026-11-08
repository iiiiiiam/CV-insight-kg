import assert from 'node:assert/strict'
import test from 'node:test'
import {feedbackOwner,readReceipts,saveReceipt} from '../src/services/feedback-receipts.ts'
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
