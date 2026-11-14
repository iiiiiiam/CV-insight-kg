import {requestJson} from './http.ts'
import {auth} from '../stores/auth.ts'
export interface GraphDraft {batch_id:string;source_batch_id:string;snapshot_revision:string;digest:string;provenance:'reviewed_export';entity_count:number;relation_count:number;paper_count:number;schema_version:string;vocabulary_version:string}
export interface GraphBatch {id:string;status:string;provenance:string;entity_count:number;relation_count:number;source_batch_id:string;checks:Record<string,boolean>;publishable:boolean;active_batch_id:string|null}
export function previewBatch(batchId:string,source:string,revision:string){return requestJson<GraphDraft>(`/api/admin/graph/preview?${new URLSearchParams({batch_id:batchId,source_batch_id:source,snapshot_revision:revision})}`,{signal:AbortSignal.timeout(35000)})}
function write(body:unknown):RequestInit{return {method:'POST',headers:{'X-CSRF-Token':auth.session?.csrf_token??''},body:JSON.stringify(body),signal:AbortSignal.timeout(35000)}}
export function importBatch(draft:GraphDraft){return requestJson<{id:string;replay:boolean}>('/api/admin/graph/import',write({batch_id:draft.batch_id,source_batch_id:draft.source_batch_id,snapshot_revision:draft.snapshot_revision,digest:draft.digest}))}
export function checkBatch(id:string){return requestJson<GraphBatch>(`/api/admin/graph/batches/${encodeURIComponent(id)}`)}
export function publishBatch(id:string,expected:string|null){return requestJson<{batch_id:string;status:string;previous_batch_id:string|null}>(`/api/admin/graph/batches/${encodeURIComponent(id)}/publish`,write({expected_active_batch_id:expected}))}
