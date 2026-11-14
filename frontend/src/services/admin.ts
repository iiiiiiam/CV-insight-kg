import { auth } from '../stores/auth.ts'
import { requestJson } from './http.ts'

export interface DatasetInfo {
  id: string
  title: string
  progress?: {total:number;succeeded:number;failed:number;pending:number;skipped:number}
  quality?: {total:number;with_abstract:number;with_doi:number;with_authors:number}
  paper_count?: number
  venue?: string
  year?: number
  checksum?: string
  raw: Record<string, unknown>
}

export interface JobInfo {
  id: number
  batch_id: number
  batch_code: string
  display_code?: string
  import_mode?: 'manual'|'automatic'
  is_simulated?: boolean
  kind: string
  dataset_id: string | null
  venue: string
  year: number
  source: string
  status: string
  stage: string
  batch_state?: string|null
  source_names?: string[]|null
  updated_papers?: number
  attempted: number
  succeeded: number
  failed: number
  error: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  progress?: {total:number;succeeded:number;failed:number;pending:number;skipped:number}
  quality?: {total:number;with_abstract:number;with_doi:number;with_authors:number}
  paper_count?: number
  events?: Array<{stage:string;level:string;message:string;created_at:string}>
}

function records(value: unknown): Record<string, any>[] {
  if (Array.isArray(value)) return value.filter(item => item && typeof item === 'object')
  if (value && typeof value === 'object') {
    const root = value as Record<string, unknown>
    const list = root.items ?? root.data ?? root.datasets ?? root.papers
    if (Array.isArray(list)) return list.filter(item => item && typeof item === 'object')
  }
  return []
}

function writeInit(method: 'POST' | 'PUT', body?: unknown): RequestInit {
  return {
    method,
    headers: { 'X-CSRF-Token': auth.session?.csrf_token ?? '' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export async function getDatasets() {
  const data = await requestJson<unknown>('/api/admin/datasets')
  return records(data).map(raw => ({
    id: String(raw.id ?? raw.dataset_id ?? raw.code ?? ''),
    title: String(raw.title ?? raw.name ?? raw.dataset_id ?? raw.id ?? '未命名基准'),
    paper_count: Number(raw.paper_count ?? raw.total_papers ?? raw.expected_count ?? raw.count) || undefined,
    venue: typeof raw.venue === 'string' ? raw.venue : undefined,
    year: Number(raw.year) || undefined,
    checksum: typeof (raw.sha256 ?? raw.checksum) === 'string' ? (raw.sha256 ?? raw.checksum) : undefined,
    raw,
  })).filter(item => item.id)
}

export async function getJobs() {
  return records(await requestJson<unknown>('/api/admin/jobs')) as unknown as JobInfo[]
}

export function importDataset(dataset_id: string) {
  return requestJson<JobInfo>('/api/admin/imports', writeInit('POST', { dataset_id }))
}

export function createOnlineJob(venue:string, year:number, start:number, count:number, source='cvf') {
  return requestJson<JobInfo>('/api/admin/jobs', writeInit('POST', {venue, year, start, count, source}))
}

export function getJob(id: number) {
  return requestJson<JobInfo>(`/api/admin/jobs/${id}`)
}

export async function getJobPapers(id: number) {
  return records(await requestJson<unknown>(`/api/admin/jobs/${id}/papers?page=1&page_size=100`))
}

export function retryJob(id: number) {
  return requestJson<JobInfo>(`/api/admin/jobs/${id}/retry`, writeInit('POST'))
}

export interface DataBatch {display_code?:string;import_mode?:'manual'|'automatic';is_simulated?:boolean;source_names?:string[]|null;batch_state?:string;updated_papers?:number;kind:string;duplicate_papers:number|null;id:number;batch_code:string;dataset_id:string|null;venue:string;year:number;source:string;status:string;stage:string;attempted:number;succeeded:number;failed:number;paper_count:number;new_papers:number|null;created_at:string;started_at:string|null;finished_at:string|null}
export interface DataOverview {demo_mode:boolean;source_summary:{name:string;papers:number;last_imported_at:string|null}[];latest_papers:{homepage_url:string|null;id:number;title:string;authors:string[];venue:string;year:number;imported_at:string}[];today_papers:number;today_added_papers?:number;today_withdrawn_papers?:number;today_net_papers?:number;failed_tasks:number;venues:{name:string;papers:number}[];total_papers:number;new_papers:number;days:number;with_abstract:number;missing_abstract:number;successful_records:number;failed_records:number;timezone:string;sources:{name:string;papers:number}[];trend:{date:string;papers:number;sources:Record<string,number>;import_modes?:{manual:number;automatic:number};added_papers?:number;added_import_modes?:{manual:number;automatic:number};withdrawn_papers?:number;withdrawn_batches?:number;net_papers?:number}[];recent_batches:DataBatch[]}
export interface BatchComparison {first:DataBatch;second:DataBatch;shared_papers:number;only_first:number;only_second:number}
export interface HandoffData {format_version:string;batch_id:number;batch_code:string;dataset_id:string|null;total_papers:number;exported_papers:number;excluded_papers:number;items:Record<string,unknown>[];excluded:{paper_id:number;title:string;reason:string}[]}
export function getDataOverview(days=7){return requestJson<DataOverview>(`/api/admin/data-overview?days=${days}`)}
export function compareDataBatches(first:number,second:number){return requestJson<BatchComparison>(`/api/admin/batch-comparison?first=${first}&second=${second}`)}
export function getHandoff(batchId:number){return requestJson<HandoffData>(`/api/admin/handoff?batch_id=${batchId}`)}
export interface NewPapers {date:string;timezone:string;total:number;page:number;page_size:number;items:{id:number;title:string;venue:string;year:number;first_seen_at:string;batch_id?:number;display_code?:string}[];withdrawals?:{batch_id:number;batch_code:string;display_code?:string;withdrawn_at:string;reason:string;removed_papers:number;retained_papers:number}[];withdrawn_papers?:number;net_papers?:number}
export function getNewPapers(day:string,page=1){return requestJson<NewPapers>(`/api/admin/new-papers?day=${encodeURIComponent(day)}&page=${page}&page_size=10&view=additions`)}

export function getBatchPapers(id:number,page=1,q=""){return requestJson<{total:number;items:Record<string,any>[]}>(`/api/admin/jobs/${id}/papers?page=${page}&page_size=20&q=${encodeURIComponent(q)}`)}

export function getSources(){return requestJson<Array<{name:string;enabled:boolean;page_size:number;max_retries:number}>>('/api/admin/sources')}
export function importPaperFile(content:string,manifest:Record<string,unknown>){return requestJson<JobInfo>('/api/admin/file-imports',{...writeInit('POST',{content,manifest}),signal:AbortSignal.timeout(120000)})}

export interface ReserveGroup {venue:string;year:number;source:string;total:number;available:number}
export interface ReserveLibrary {items:ReserveGroup[];available:number}
export function getReserve(){return requestJson<ReserveLibrary>('/api/admin/reserve')}
export function importReserve(group:ReserveGroup,count:number){return requestJson<JobInfo & {selected_papers:number}>('/api/admin/reserve/imports',writeInit('POST',{venue:group.venue,year:group.year,source:group.source,count}))}

export interface FormalBatch {batch_id:number;batch_key:string;state:'active'|'withdrawn';status:string;withdrawal_reason:string|null;withdrawn_at:string|null;counts:Record<string,number>}
export function getFormalBatch(id:number){return requestJson<FormalBatch>(`/api/admin/formal/batches/${id}`)}
export function withdrawFormalBatch(id:number,reason:string){return requestJson<FormalBatch>(`/api/admin/formal/batches/${id}/withdraw`,writeInit('POST',{reason}))}
export interface BatchWithdrawal {display_code?:string;import_mode?:'manual'|'automatic';is_simulated?:boolean;batch_id:number;batch_code:string;state:'active'|'withdrawn';withdrawal_reason:string|null;withdrawn_at:string|null;can_withdraw:boolean;blocked_reason:string}
export function getBatchWithdrawal(id:number){return requestJson<BatchWithdrawal>(`/api/admin/jobs/${id}/withdrawal`)}
export function withdrawImportBatch(id:number,reason:string){return requestJson<BatchWithdrawal>(`/api/admin/jobs/${id}/withdraw`,writeInit('POST',{reason}))}

export function updateSource(name:string,value:{enabled:boolean;page_size:number;max_retries:number}){return requestJson(`/api/admin/sources/${encodeURIComponent(name)}`,writeInit('PUT',value))}
export interface QualityData {total_papers:number;issue_count:number;issues:{id:number;title:string;venue:string;year:number;missing:string[]}[];coverage:Record<string,any>[]}
export function getQuality(){return requestJson<QualityData>('/api/admin/quality',{signal:AbortSignal.timeout(30000)})}
export interface ReceiptData {batch_revision:string;state:string;items:{recipient:string;status:string;message:string;snapshot_revision:string|null;updated_at:string;current:boolean}[]}
export function getReceipts(id:number){return requestJson<ReceiptData>(`/api/admin/formal/batches/${id}/receipts`)}

export interface TaskRecords {total:number;page:number;page_size:number;items:{id:number;source:string;source_id:string;status:string;stage:string;attempts:number|null;error:string|null}[]}
export function getTaskRecords(id:number,page=1,status='failed'){return requestJson<TaskRecords>(`/api/admin/jobs/${id}/records?page=${page}&page_size=10${status?'&status='+status:''}`)}
