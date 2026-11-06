import {requestJson} from './http.ts'
import type {Evidence,EntityContent,RelationContent} from './knowledge.ts'

export interface KnowledgeItem {
  candidate_id:string;content:EntityContent|RelationContent;evidence:Evidence[]
}
export interface ReadingKnowledge {
  paper:{openalex_id:string;title:string;abstract:string|null;year:number;venue:string;source_url:string}
  entities:KnowledgeItem[];relations:KnowledgeItem[];revision:string;vocabulary_version:string
}
export interface FeedbackRecord {
  id:string;paper_id:string;paper_title:string;candidate_id:string|null;term:string|null;message:string
  status:'open'|'resolved'|'dismissed';created_at:string;updated_at:string
  context:Record<string,unknown>
  resolution:null|{action:string;reason:string;reviewer:string;occurred_at:string;before:unknown;after:unknown}
}
export interface FeedbackQueue {
  revision:number;requests:FeedbackRecord[];counts:Record<FeedbackRecord['status'],number>
  terms:Array<{term:{name:string;kind:string;aliases:string[]};source_url:string;created_at:string}>
}
export const RELATION_NAMES:Record<string,string>={has_author:'作者',affiliated_with:'机构关联',published_in:'发表于',mentions_topic:'提及主题',mentions_method:'提及方法',mentions_task:'提及任务',mentions_dataset:'提及数据集'}
export const KIND_NAMES:Record<string,string>={paper:'论文',author:'作者',institution:'机构',venue:'会议/期刊',topic:'主题',method:'方法',task:'任务',dataset:'数据集'}
export function itemName(item:KnowledgeItem,view:ReadingKnowledge):string {
  const content=item.content
  if('name' in content)return content.name
  const names=new Map(view.entities.map(e=>{const c=e.content as EntityContent;return [c.key,c.name]}))
  return `${names.get(content.source)??content.source} → ${RELATION_NAMES[content.kind]??content.kind} → ${names.get(content.target)??content.target}`
}
export function getReading(paperId:string,signal?:AbortSignal){
  return requestJson<ReadingKnowledge>(`/api/knowledge/paper?${new URLSearchParams({paper_id:paperId})}`,{signal})
}
export function getReadingPapers(signal?:AbortSignal){
  return requestJson<Array<{paper_id:string;title:string;year:number;venue:string}>>('/api/knowledge/papers',{signal})
}
export function sendFeedback(body:{paper_id:string;revision:string;message:string;candidate_id?:string;term?:string}){
  return requestJson<{id:string;status:string;duplicate:boolean}>('/api/knowledge/feedback',{method:'POST',body:JSON.stringify(body)})
}
export function getFeedbackQueue(){return requestJson<FeedbackQueue>('/api/admin/knowledge/feedback')}
export function resolveFeedback(id:string,body:{revision:number;action:string;reason:string;name?:string;kind?:string;source_url?:string;aliases?:string[]},csrf:string){
  return requestJson(`/api/admin/knowledge/feedback/${id}`,{method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify(body)})
}
