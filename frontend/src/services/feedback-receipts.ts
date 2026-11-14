import type {FeedbackRecord} from './knowledge-feedback.ts'
import type {LocalStoragePort} from './personal-knowledge.ts'

const OWNER_KEY='research-insight:feedback-owner:1'
export interface FeedbackReceipt {id:string;message:string;status:FeedbackRecord['status'];created_at:string}
export function receiptKey(paperId:string){return `research-insight:feedback-receipts:1:${paperId}`}
export function feedbackOwner(storage:LocalStoragePort):string{
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
  if(existing)existing.status=receipt.status
  else items.unshift(receipt)
  storage.setItem(receiptKey(paperId),JSON.stringify(items))
}
