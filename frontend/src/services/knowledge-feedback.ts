import {ApiError,requestJson} from './http.ts'
import type {Evidence,EntityContent,RelationContent} from './knowledge.ts'

const FEEDBACK_READ_TIMEOUT=120000
const FEEDBACK_WRITE_TIMEOUT=300000

export interface KnowledgeItem {
  candidate_id:string;content:EntityContent|RelationContent;evidence:Evidence[]
}
export interface SourceClassification {
  kind:string;name:string;source:string;source_url:string;source_id:string
  parent_name?:string;selection?:'primary'|'additional'|'fallback'
  mapped_from?:Array<{channel?:string;name:string;quote?:string;source_url?:string;source_path:Array<string|number>}>
}
export interface ReadingKnowledge {
  paper:{openalex_id:string;title:string;abstract:string|null;year:number;venue:string;source_url:string}
  entities:KnowledgeItem[];relations:KnowledgeItem[];revision:string;vocabulary_version:string
  source_enrichment?:{
    source_classifications:SourceClassification[]
    source_records:Array<{source:string;url:string;fetched_at:string;digest:string}>
    accepted_signals:Array<{key:string;name:string;source:string;source_url:string;alias:string}>
    added_entities:EntityContent[]
    fallback_matches?:Array<{key:string;kind:string;name:string;source_url:string;alias:string}>
    text_signals?:Array<{kind:string;name:string;alias:string;field:string;context:string;rule:string}>
  }
}
export interface FeedbackRecord {
  id:string;paper_id:string;paper_title:string;candidate_id:string|null;term:string|null;message:string
  status:'open'|'resolved'|'dismissed'|'withdrawn';created_at:string;updated_at:string
  cloud?:{id:string;revision:number;reply:string;delivery:string;can_apply:boolean;warning:string;local_id:string|null;can_reopen:boolean}
  context:Record<string,unknown>
  resolution:null|{action:string;reason:string;reviewer:string;occurred_at:string;before:unknown;after:unknown}
  processing_history?:Array<{resolution:NonNullable<FeedbackRecord['resolution']>;reopened_by:string;reopened_at:string}>
}
export interface FeedbackQueue {
  revision:number;requests:FeedbackRecord[];counts:Record<Exclude<FeedbackRecord['status'],'withdrawn'>,number>
  terms:Array<{term:{name:string;kind:string;aliases:string[]};source_url:string;created_at:string}>
}
export interface CloudFeedbackRecord {
  id:string;status:FeedbackRecord['status'];processing_note:string;state_revision:number;created_at:string;updated_at:string
}
export interface CloudReceipt {delivery:'pending'|'sent';feedback:CloudFeedbackRecord|null}
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
export interface DirectionPaper {paper_id:string;title:string;year:number;venue:string;research_directions:Array<{id:string;name:string}>}
export function getReadingDirections(signal?:AbortSignal){
  return requestJson<{directions:Array<{id:string;name:string;count:number}>;papers:DirectionPaper[]}>('/api/knowledge/research-directions',{
    signal:signal??AbortSignal.timeout(FEEDBACK_READ_TIMEOUT),
  })
}
export function sendFeedback(body:{paper_id:string;revision:string;message:string;candidate_id?:string;term?:string;owner_token?:string}){
  return requestJson<{id:string;status:FeedbackRecord['status'];message?:string;duplicate:boolean;cloud?:CloudReceipt;cloud_error?:string}>('/api/knowledge/feedback',{
    method:'POST',body:JSON.stringify(body),signal:AbortSignal.timeout(FEEDBACK_READ_TIMEOUT),
  })
}
export function getFeedbackStatus(id:string,owner?:string){
  return requestJson<{id:string;status:FeedbackRecord['status'];updated_at:string;cloud?:CloudReceipt|null}>(`/api/knowledge/feedback/${encodeURIComponent(id)}`,{
    ...(owner?{headers:{'X-Feedback-Owner':owner}}:{}),
    signal:AbortSignal.timeout(FEEDBACK_READ_TIMEOUT),
  })
}
export function exchangeCloudFeedback(id:string,owner_token:string,operation:'send'|'refresh'){
  return requestJson<CloudReceipt>(`/api/knowledge/feedback/${encodeURIComponent(id)}/cloud/${operation}`,{
    method:'POST',body:JSON.stringify({owner_token}),signal:AbortSignal.timeout(20000),
  })
}
export function getCloudFeedbackConfig(){return requestJson<{enabled:boolean;team_enabled:boolean;account_management:boolean;team_username:string|null}>('/api/admin/knowledge/cloud-feedback/config')}
export interface TeamAccount {username:string;role:'owner'|'admin';enabled:boolean;revision:number;created_at:string;updated_at:string}
function teamAccountRequest<T>(path:string,body:unknown,csrf:string){return requestJson<T>('/api/admin/knowledge/cloud-feedback/'+path,{
  method:'POST',headers:{'X-CSRF-Token':csrf},...(body===undefined?{}:{body:JSON.stringify(body)}),signal:AbortSignal.timeout(20000),
})}
export function listTeamAccounts(csrf:string){return teamAccountRequest<{accounts:TeamAccount[];current_username:string}>('accounts/refresh',undefined,csrf)}
export function createTeamAccount(body:{username:string;password:string;role:'owner'|'admin'},csrf:string){return teamAccountRequest<{account:TeamAccount}>('accounts/create',body,csrf)}
export function updateTeamAccount(username:string,body:{expected_revision:number;role?:'owner'|'admin';enabled?:boolean;new_password?:string},csrf:string){return teamAccountRequest<{account:TeamAccount}>(`accounts/${encodeURIComponent(username)}/update`,body,csrf)}
export function changeTeamPassword(body:{current_password:string;new_password:string},csrf:string){return teamAccountRequest<{account:TeamAccount}>('password',body,csrf)}
export function refreshCloudFeedback(csrf:string){return requestJson<{requests:Array<CloudFeedbackRecord&{payload:Record<string,string>}>}>('/api/admin/knowledge/cloud-feedback/refresh',{
  method:'POST',headers:{'X-CSRF-Token':csrf},signal:AbortSignal.timeout(20000),
})}
export function replyCloudFeedback(id:string,body:{status:string;processing_note:string;expected_revision:number},csrf:string){
  return requestJson<CloudFeedbackRecord>(`/api/admin/knowledge/cloud-feedback/${encodeURIComponent(id)}/reply`,{
    method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify(body),signal:AbortSignal.timeout(20000),
  })
}
export function withdrawFeedback(id:string,ownerToken:string){
  return requestJson<{id:string;status:FeedbackRecord['status']}>(`/api/knowledge/feedback/${encodeURIComponent(id)}/withdraw`,{
    method:'POST',body:JSON.stringify({owner_token:ownerToken}),signal:AbortSignal.timeout(FEEDBACK_READ_TIMEOUT),
  })
}
export function getFeedbackQueue(){return requestJson<FeedbackQueue>('/api/admin/knowledge/feedback',{
  signal:AbortSignal.timeout(FEEDBACK_READ_TIMEOUT),
})}
export function resolveFeedback(id:string,body:{revision:number;cloud_revision?:number;action:string;reason:string;name?:string;kind?:string;source_url?:string;aliases?:string[]},csrf:string){
  return requestJson<{message?:string;reply_delivery?:string}>(`/api/admin/knowledge/feedback/${encodeURIComponent(id)}`,{
    method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify(body),signal:AbortSignal.timeout(FEEDBACK_WRITE_TIMEOUT),
  })
}
export function reopenFeedback(id:string,revision:number,csrf:string,cloud_revision?:number){
  return requestJson<{id:string;status:'open';message?:string;reply_delivery?:string}>(`/api/admin/knowledge/feedback/${encodeURIComponent(id)}/reopen`,{
    method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({revision,cloud_revision}),signal:AbortSignal.timeout(FEEDBACK_WRITE_TIMEOUT),
  })
}

export async function downloadEffectiveKnowledge(){
  const response=await fetch('/api/admin/knowledge/effective-export',{
    credentials:'same-origin',signal:AbortSignal.timeout(180000),
  })
  if(!response.ok){
    const body=await response.json().catch(()=>null)
    throw new ApiError(body?.error?.message??body?.detail??`导出失败（${response.status}）`,response.status)
  }
  const revision=response.headers.get('X-Knowledge-Revision')??''
  if(!response.headers.get('Content-Type')?.includes('application/json')||!/^[0-9a-f]{64}$/.test(revision))throw new Error('导出响应不完整，请重新导出。')
  return {blob:await response.blob(),filename:`effective-${revision.slice(0,12)}.json`}
}

export function refreshTeamFeedback(csrf:string){return requestJson<FeedbackQueue>("/api/admin/knowledge/feedback/team-refresh",{method:"POST",headers:{"X-CSRF-Token":csrf},signal:AbortSignal.timeout(20000)})}
export function retryTeamReply(id:string,csrf:string){return requestJson<{message:string}>(`/api/admin/knowledge/feedback/${encodeURIComponent(id)}/reply-retry`,{method:"POST",headers:{"X-CSRF-Token":csrf},signal:AbortSignal.timeout(20000)})}
