import { auth } from '../stores/auth.ts'
import { requestJson } from './http.ts'

export interface DatasetInfo {
  id: string
  title: string
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
  kind: string
  dataset_id: string | null
  venue: string
  year: number
  source: string
  status: string
  stage: string
  attempted: number
  succeeded: number
  failed: number
  error: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
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

export function getJob(id: number) {
  return requestJson<JobInfo>(`/api/admin/jobs/${id}`)
}

export async function getJobPapers(id: number) {
  return records(await requestJson<unknown>(`/api/admin/jobs/${id}/papers?page=1&page_size=100`))
}

export function retryJob(id: number) {
  return requestJson<JobInfo>(`/api/admin/jobs/${id}/retry`, writeInit('POST'))
}
