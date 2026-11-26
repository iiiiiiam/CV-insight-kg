import {auth} from '../stores/auth.ts'
import {requestJson} from './http.ts'
import type {WorkflowTask} from './workflows.ts'

export interface OnlineCollection {
 id:number;venue:string;year:number;status:string;stage:string;display_code:string
 requested_count:number;selected_count:number;scanned_count:number;existing_count:number;skipped_count:number
 keyword:string;imported_count:number;new_count:number;failed_count:number;progress:number;error:string|null
 next_retry_at:string|null;background_task:WorkflowTask|null
}
export function collectOnline(body:{request_key:string;venue:string;year:number;count:number;keyword:string}){
 return requestJson<OnlineCollection>('/api/admin/online-collections',{method:'POST',
  headers:{'X-CSRF-Token':auth.session?.csrf_token??''},body:JSON.stringify(body)})
}
export function getOnlineCollection(id:number){
 return requestJson<OnlineCollection>(`/api/admin/online-collections/${id}`)
}
