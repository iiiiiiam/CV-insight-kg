import {requestJson} from './http.ts'

export interface BatchReceipt {
  status:string;accepted?:number;new?:number;updated?:number;duplicates?:number
  removed?:number;retained?:number;restored?:number;failed?:number;not_applied?:number
  errors?:Array<{index:number|null;reason:string}>
}
export interface BatchStatus {
  revision:number;managed:boolean;paper_count:number;snapshot_revision:string
  batches:Array<{batch_code:string;active:boolean;paper_count:number;receipt:BatchReceipt}>
  failures:Array<{occurred_at:string;batch_code:string|null;result:BatchReceipt}>
  source_enrichment:{total:number;completed:number;pending:number;with_sources:number;partial:number;running:boolean;error:string|null}
}
const endpoint='/api/admin/knowledge/batches'
export function getKnowledgeBatches(){return requestJson<BatchStatus>(endpoint,{signal:AbortSignal.timeout(180000)})}
export function enrichKnowledgeBatches(csrf:string){return requestJson(`${endpoint}/enrich`,{
  method:'POST',headers:{'X-CSRF-Token':csrf},signal:AbortSignal.timeout(180000)})}
export function importKnowledgeBatch(document:Record<string,unknown>,revision:number,csrf:string){
  return requestJson<BatchReceipt>(endpoint,{method:'POST',headers:{'X-CSRF-Token':csrf},
    body:JSON.stringify({document,revision,acknowledge_switch:true}),signal:AbortSignal.timeout(180000)})
}
export function withdrawKnowledgeBatch(code:string,revision:number,csrf:string){
  return requestJson<BatchReceipt>(`${endpoint}/${encodeURIComponent(code)}/withdraw`,{
    method:'POST',headers:{'X-CSRF-Token':csrf},body:JSON.stringify({revision}),signal:AbortSignal.timeout(180000)})
}
