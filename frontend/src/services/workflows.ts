/** A-owned task adapters for D's report and handoff pages. */
import {auth} from '../stores/auth.ts'
import {requestJson} from './http.ts'

export type TaskStatus = 'queued'|'running'|'succeeded'|'failed'
export interface WorkflowTask {
  id:string; kind:'report'|'handoff'; title:string|null; batch_id:number|null
  batch_revision:string|null; status:TaskStatus; stage:string; progress:number; attempts:number
  error:string|null; created_at:string; updated_at:string; finished_at:string|null
  events:Array<{at:string;attempt:number;stage:string;progress:number;message:string}>
  result:Record<string,unknown>|null
}
export interface ReportSection {
  provider:'B'|'C'; revision:string; paper_ids:string[]; data:Record<string,unknown>
}
export interface ReportRequest {
  request_key:string; title?:string
  scope?:{batch_ids?:number[]; venues?:Array<'CVPR'|'ICCV'|'ECCV'>; years?:number[];paper_ids?:string[]}
  sections?:ReportSection[]
}
export interface TaskList {total:number;page:number;page_size:number;items:WorkflowTask[]}
export interface PipelineStage {status:string;message:string;revision?:string;batch_id?:string;source_enrichment?:Record<string,unknown>;results?:Record<string,unknown>}
export interface PipelineState {task_id:string;stages:Record<'A'|'B'|'C',PipelineStage>;error?:string}
export interface PublicationBatch {
  id:string;status:string;source_revision:string|null;source_batch_id?:string|null;provenance?:string|null
  schema_version?:string|null;paper_count?:number|null;entity_count?:number|null;relation_count?:number|null
  created_at?:string|null;published_at?:string|null;last_activated_at?:string|null
}
export interface PublicationStatus {
  active_batch_id:string|null;active:PublicationBatch|null;publish_generation:number
  items:PublicationBatch[];total:number;page:number;page_size:number
}
function post<T>(url:string,body?:unknown){
  return requestJson<T>(url,{method:'POST',headers:{'X-CSRF-Token':auth.session?.csrf_token??''},
    body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(120000)})
}
export function createReport(body:ReportRequest){return post<WorkflowTask>('/api/admin/reports',body)}
export function listTasks(kind:'reports'|'handoffs',page=1,status?:TaskStatus){
  const query=new URLSearchParams({page:String(page)})
  if(status)query.set('status',status)
  return requestJson<TaskList>(`/api/admin/${kind}?${query}`)
}
export function getTask(kind:'reports'|'handoffs',id:string,signal?:AbortSignal){
  return requestJson<WorkflowTask>(`/api/admin/${kind}/${encodeURIComponent(id)}`,{signal})
}
export function retryTask(kind:'reports'|'handoffs',id:string){return post<WorkflowTask>(`/api/admin/${kind}/${encodeURIComponent(id)}/retry`)}
export function reportDownloadUrl(id:string){return `/api/admin/reports/${encodeURIComponent(id)}/download`}
export function reportFileUrl(id:string,filename:string){return `/api/admin/reports/${encodeURIComponent(id)}/files/${encodeURIComponent(filename)}`}
export function createHandoff(batchId:number,revision:string,requestKey:string){
  return post<WorkflowTask>('/api/admin/handoffs',{batch_id:batchId,expected_revision:revision,
    request_key:requestKey,acknowledge_switch:true})
}
export function getPipeline(id:string){
  return requestJson<PipelineState>(`/api/admin/handoffs/${encodeURIComponent(id)}/pipeline`)
}
export function getPublicationStatus(page=1){
  return requestJson<PublicationStatus>(`/api/admin/graph/publication-status?${new URLSearchParams({page:String(page),page_size:'20'})}`)
}
export function getBReportInput(expectedRevision?:string){
  return requestJson<ReportSection>('/api/admin/report-inputs/B'+(expectedRevision?`?expected_revision=${encodeURIComponent(expectedRevision)}`:''),{signal:AbortSignal.timeout(120000)})
}
export function getCReportInput(expectedRevision:string){
  return requestJson<ReportSection>(`/api/admin/report-inputs/C?expected_revision=${encodeURIComponent(expectedRevision)}`,{signal:AbortSignal.timeout(120000)})
}
