import type {FeedbackRecord,CloudReceipt} from './knowledge-feedback.ts'
import type {LocalStoragePort} from './personal-knowledge.ts'

const OWNER_KEY='research-insight:feedback-owner:1'
export interface FeedbackReceipt {id:string;message:string;status:FeedbackRecord['status'];created_at:string;cloud?:CloudReceipt|null}
export function feedbackDisplayStatus(receipt:FeedbackReceipt):FeedbackRecord['status']{
  return receipt.cloud?.delivery==='sent'&&receipt.cloud.feedback?receipt.cloud.feedback.status:receipt.status
}
export function receiptKey(paperId:string){return `research-insight:feedback-receipts:1:${paperId}`}
export function feedbackOwner(storage:LocalStoragePort,authenticated?:string):string{
  if(authenticated){if(!/^[0-9a-f]{64}$/.test(authenticated))throw new Error('当前账号的反馈凭证无法读取。');return authenticated}
  const saved=storage.getItem(OWNER_KEY)
  if(saved){if(!/^[0-9a-f]{64}$/.test(saved))throw new Error('当前浏览器的反馈凭证无法读取。');return saved}
  const token=(crypto.randomUUID()+crypto.randomUUID()).replaceAll('-','')
  storage.setItem(OWNER_KEY,token)
  return token
}
export function readReceipts(storage:LocalStoragePort,paperId:string):FeedbackReceipt[]{
  const body=storage.getItem(receiptKey(paperId));if(!body)return []
  const items=JSON.parse(body) as FeedbackReceipt[]
  if(!Array.isArray(items)||items.some(item=>!item||typeof item.id!=='string'||typeof item.message!=='string'
    ||typeof item.created_at!=='string'||!['open','resolved','dismissed','withdrawn'].includes(item.status)))throw new Error('当前浏览器的反馈记录无法读取，原记录已保留。')
  return items
}
export function saveReceipt(storage:LocalStoragePort,paperId:string,receipt:FeedbackReceipt){
  const items=readReceipts(storage,paperId),existing=items.find(item=>item.id===receipt.id)
  if(existing){existing.status=receipt.status;if(receipt.cloud!==undefined)existing.cloud=receipt.cloud}
  else items.unshift(receipt)
  storage.setItem(receiptKey(paperId),JSON.stringify(items))
}

// Keep each cached receipt visible when an unrelated status request fails.
export async function refreshReceipts(items:FeedbackReceipt[],lookup:(id:string)=>Promise<{status:FeedbackRecord['status'];cloud?:CloudReceipt|null}>){
  return Promise.all(items.map(async item=>{
    try{const result=await lookup(item.id);return {...item,status:result.status,cloud:result.cloud??item.cloud,refresh_error:'',archived:false}}
    catch(e){if(item.status==='withdrawn'&&e instanceof Error&&'status' in e&&e.status===404)return {...item,refresh_error:'',archived:true};return {...item,archived:false,refresh_error:e instanceof Error?e.message:'状态读取失败，请稍后重试。'}}
  }))
}
