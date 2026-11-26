import {auth} from '../stores/auth.ts'
import {requestJson} from './http.ts'

export interface CollectionPlan {
  id:string;enabled:boolean;time:string;timezone:string;scopes:string[];with_annotations:boolean
  max_attempts:number;retry_seconds:number;revision:string;next_run_local:string;next_run_utc:string
}
export interface CollectionRecord {
  run_id:number;schedule_id:string;scheduled_for_utc:string;trigger:string;status:string
  tasks:Array<{venue:string;year:number;status:string;attempts:number;retry_round:number;job_id:number|null
    display_code:string|null;batch_state:string|null;collected_records:number;unchanged_records:number
    error:string|null;next_attempt_utc:string|null;progress:{total:number;finished:number;percent:number}}>
}
export interface ScheduleData {
  schedules:CollectionPlan[];runs:CollectionRecord[]
  runtime:{connected:boolean;state:string;error:string|null;last_seen_utc:string|null}
}
export function getSchedules(signal?:AbortSignal){return requestJson<ScheduleData>('/api/admin/formal/schedules',{signal})}
function write<T>(url:string,method:'POST'|'PUT',body?:unknown){
  return requestJson<T>(url,{method,headers:{'X-CSRF-Token':auth.session?.csrf_token??''},
    body:body===undefined?undefined:JSON.stringify(body)})
}
export function saveSchedule(plan:Omit<CollectionPlan,'revision'|'next_run_local'|'next_run_utc'>,revision:string|null){
  const {id,...config}=plan
  return write<ScheduleData>(`/api/admin/formal/schedules/${encodeURIComponent(id)}`,'PUT',{...config,expected_revision:revision})
}
export function runSchedule(id:string){return write<{run_id:number;replay:boolean}>(`/api/admin/formal/schedules/${encodeURIComponent(id)}/run`,'POST')}
export function retryCollection(id:number){return write<{run_id:number;retried_tasks:number}>(`/api/admin/formal/collection-runs/${id}/retry`,'POST')}
