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
  return requestJson<{task_id:string;stages:Record<string,{status:string;message:string}>}>(`/api/admin/handoffs/${encodeURIComponent(id)}/pipeline`)
}
export function getBReportInput(expectedRevision?:string){
  return requestJson<ReportSection>('/api/admin/report-inputs/B'+(expectedRevision?`?expected_revision=${encodeURIComponent(expectedRevision)}`:''),{signal:AbortSignal.timeout(120000)})
}
export function getCReportInput(expectedRevision:string){
  return requestJson<ReportSection>(`/api/admin/report-inputs/C?expected_revision=${encodeURIComponent(expectedRevision)}`,{signal:AbortSignal.timeout(120000)})
}
