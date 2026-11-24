import { ApiError, requestJson } from './http.ts'

export interface Evidence {
  paper_id: string; dataset_id: string; source_url: string; input_fingerprint: string;
  field: 'title' | 'abstract' | 'metadata'; quote: string;
  start: number | null; end: number | null; path: Array<string | number>;
}
export interface Candidate {
  candidate_id: string; status: 'pending'; evidence: Evidence[];
  entity?: { key: string; kind: string; name: string; source_id: string | null };
  source?: string; kind?: string; target?: string;
}
export type ReviewStatus = 'pending' | 'confirmed' | 'rejected'
export type CandidateKind = 'entities' | 'relations'
export type ViewMode = 'reviewed' | 'original'
export type ReviewAction = 'confirm' | 'reject' | 'correct' | 'reopen'
export type ExportFormat = 'confirmed.json' | 'pending.json' | 'rejected.json' | 'bundle.zip'
export interface EntityContent {key: string; kind: string; name: string; source_id: string | null}
export interface RelationContent {source: string; kind: string; target: string}
export interface ReviewItem {
  candidate_id: string; content: EntityContent | RelationContent; evidence: Evidence[]; status: ReviewStatus;
}
export interface ReviewEvent {
  sequence: number; action: string; reviewer: string; reason: string; occurred_at: string;
  before: ReviewItem; after: ReviewItem;
}
export type ReviewCounts = Record<ReviewStatus, {entities: number; relations: number}>
export interface DisplayCandidate extends Omit<Candidate, 'status'> {
  status: ReviewStatus; changed_fields: string[];
}
export const STATUS_LABELS: Record<ReviewStatus, string> = {pending: '待审核', confirmed: '已确认', rejected: '已驳回'}
export const ACTION_LABELS: Record<string, string> = {
  confirm: '确认', reject: '驳回', correct: '纠正', reopen: '撤回决定', reopen_dependency: '随端点撤回重审',
}
export interface KnowledgeOverview {
  dataset_id: string; schema_version: string; rule_version: string; vocabulary_version: string;
  vocabulary_fingerprint: string; entity_count: number; relation_count: number; diagnostic_count: number;
  confirmed_count: number; read_only: true; status: 'review_snapshot';
  review_counts: ReviewCounts; review_version: string; snapshot_revision: string; loaded_at: string;
  papers: Array<{openalex_id: string; title: string; year: number; venue: string; entity_count: number; relation_count: number}>;
}
export interface KnowledgeDetail {
  paper: {openalex_id: string; title: string; abstract: string | null; year: number; venue: string; authorships: unknown[]; source_url: string; dataset_id: string};
  result: {paper_id: string; input_fingerprint: string; schema_version: string; rule_version: string;
    vocabulary_version: string; vocabulary_fingerprint: string; entities: Candidate[]; relations: Candidate[]; diagnostics: string[]};
  review: {version: string; counts: ReviewCounts; has_archive: boolean; archive_revision: string | null;
    items: ReviewItem[]; history: ReviewEvent[]};
  snapshot_revision: string; loaded_at: string;
  read_only: true; confirmed_count: number; scope: 'fixed_snapshot'; notice: string;
}
export function getKnowledgeOverview(signal?: AbortSignal) {
  return requestJson<KnowledgeOverview>('/api/admin/knowledge/snapshot', {signal})
}
export function getKnowledgeDetail(paperId: string, signal?: AbortSignal, revision?: string) {
  const query = new URLSearchParams({paper_id: paperId})
  if (revision) query.set('snapshot_revision', revision)
  return requestJson<KnowledgeDetail>(`/api/admin/knowledge/candidates?${query}`, {signal})
}

export function submitKnowledgeReview(body:{paper_id:string;candidate_id:string;action:ReviewAction;reason:string;snapshot_revision:string;name?:string},csrfToken:string) {
  return requestJson<{saved:true;archive_revision:string;snapshot_revision:string;affected_candidate_ids:string[]}>(
    '/api/admin/knowledge/reviews',{method:'POST',headers:{'X-CSRF-Token':csrfToken},body:JSON.stringify(body)})
}

export async function fetchKnowledgeDownload(format:ExportFormat,revision:string):Promise<Blob> {
  const query=new URLSearchParams({snapshot_revision:revision})
  const response=await fetch(`/api/admin/knowledge/exports/${format}?${query}`,{
    credentials:'same-origin',signal:AbortSignal.timeout(30000),
  })
  if(!response.ok){
    const payload=await response.json().catch(()=>null)
    throw new ApiError(payload?.error?.message??`下载失败（${response.status}）`,response.status,payload?.request_id??'')
  }
  return response.blob()
}

export interface ConfirmedKnowledge {
  paper_id:string;supported:boolean;scope:'fixed_snapshot';entities:ReviewItem[];relations:ReviewItem[];
  source?:{title:string;abstract:string|null;source_url:string};dataset_id?:string;vocabulary_version?:string;
  snapshot_revision?:string;notice:string;
}
export function getConfirmedKnowledge(paperId:string,signal?:AbortSignal){
  return requestJson<ConfirmedKnowledge>(`/api/knowledge/confirmed?${new URLSearchParams({paper_id:paperId})}`,{signal})
}

// The raw result keeps B's pending candidates. ReviewItem content is adapted separately.
export function candidateRows(detail: KnowledgeDetail, kind: CandidateKind, mode: ViewMode, status: ReviewStatus | 'all' = 'all'): DisplayCandidate[] {
  const originals = detail.result[kind]
  if (mode === 'original') return originals.filter(() => status === 'all' || status === 'pending').map(c => ({...c, changed_fields: []}))
  const originalById = new Map(originals.map(c => [c.candidate_id, c]))
  return detail.review.items.filter(item => (kind === 'entities') === ('key' in item.content))
    .filter(item => status === 'all' || status === item.status).map(item => {
      const original = originalById.get(item.candidate_id)
      const entity = 'key' in item.content ? item.content : undefined
      const relation = 'source' in item.content ? item.content : undefined
      const changed: string[] = []
      if (entity && original?.entity && entity.name !== original.entity.name) changed.push('名称')
      if (original && JSON.stringify(item.evidence) !== JSON.stringify(original.evidence)) changed.push('证据')
      return {candidate_id: item.candidate_id, status: item.status, evidence: item.evidence,
        entity, source: relation?.source, kind: relation?.kind, target: relation?.target, changed_fields: changed}
    })
}

export function candidateLabel(detail: KnowledgeDetail, item: DisplayCandidate, mode: ViewMode): string {
  if (item.entity) return item.entity.name
  const names = mode === 'original'
    ? new Map(detail.result.entities.map(c => [c.entity?.key, c.entity?.name]))
    : new Map(detail.review.items.filter(c => 'key' in c.content).map(c => {
      const content = c.content as EntityContent
      return [content.key, content.name]
    }))
  return `${names.get(item.source ?? '') ?? item.source} → ${item.kind} → ${names.get(item.target ?? '') ?? item.target}`
}

// B uses Python Unicode code point offsets, not JavaScript UTF-16 offsets.
export function evidenceExcerpt(text: string, evidence: Evidence) {
  const chars = Array.from(text), {start, end} = evidence
  if (!Number.isInteger(start) || !Number.isInteger(end) || start === null || end === null || start < 0 || end < start || end > chars.length) return null
  const quote = chars.slice(start, end).join('')
  if (quote !== evidence.quote) return null
  return {before: chars.slice(0, start).join(''), quote, after: chars.slice(end).join('')}
}
