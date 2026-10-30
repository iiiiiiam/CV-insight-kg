import type { Filters, GraphData, GraphNode, Paper, ResearchGateway } from '../types.ts'
import { requestJson } from './http.ts'

const env = import.meta.env ?? {}
const base = (env.VITE_RESEARCH_API_BASE || '/api').replace(/\/$/, '')
export const DATA_MODE = 'api'
type RecordValue = Record<string, any>
function record(value: unknown): RecordValue {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {}
}
function text(value: unknown, fallback = '—'): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}
export function safeSourceUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null }
  catch { return null }
}
function range(filters: Filters) { return filters.batch_id ? `批次 ID ${filters.batch_id}` : 'A 当前数据库' }
export function normalizePaper(value: unknown): Paper {
  const raw = record(value)
  if (raw.id === undefined || raw.id === null || String(raw.id) === '') throw new Error('A 接口返回的论文缺少 id。')
  const authors = (Array.isArray(raw.authors) ? raw.authors : [])
    .map((a: unknown) => typeof a === 'string' ? a : text(record(a).name, '')).filter(Boolean)
  const sources = (Array.isArray(raw.sources) ? raw.sources : []).map((s: unknown) => {
    const item = record(s)
    return { name: text(item.name), source_id: text(item.source_id), url: safeSourceUrl(item.url), retrieved_at: text(item.retrieved_at) }
  })
  const batchIds = Array.isArray(raw.batch_ids) ? raw.batch_ids : []
  return {
    id: String(raw.id), title: text(raw.title, '未命名论文'), year: Number(raw.year) || 0,
    venue: text(raw.venue), authors, abstract: text(raw.abstract, 'A 暂未提供摘要。'),
    topic: '待 B 审核', method: '待 B 审核', task: '待 B 审核', dataset: '待 B 审核', institution: '待 B 审核',
    source: sources.map((s: {name: string}) => s.name).join(' / ') || (raw.openalex_id ? 'OpenAlex' : '来源见 A 记录'),
    source_url: safeSourceUrl(raw.source_url), sources,
    openalex_id: text(raw.openalex_id, ''), doi: text(raw.doi, ''), canonical_key: text(raw.canonical_key, ''),
    evidence: '当前展示 A 的论文元数据；B 提及候选须人工审核，C 正式图谱待接入。',
    batch_id: batchIds.length ? String(batchIds[0]) : '—', batch_ids: batchIds,
    batches: Array.isArray(raw.batches) ? raw.batches : [],
  }
}

export function normalizeMetadataGraph(value: unknown, filters: Filters): GraphData {
  const raw = record(value)
  if (raw.basis !== 'paper_metadata' || !Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) {
    throw new Error('A 元数据图谱格式不符合接口约定。')
  }
  const aliases = new Map<string, string>()
  const nodes: GraphNode[] = raw.nodes.map((value: unknown) => {
    const node = record(value)
    if (!['Paper', 'Venue'].includes(node.type)) throw new Error('当前接口仅支持 A 的论文与会议元数据。')
    const id = node.type === 'Paper' ? String(node.paper_id) : String(node.id)
    if (!id || id === 'undefined') throw new Error('元数据节点缺少标识。')
    aliases.set(String(node.id), id)
    return { id, type: node.type, label: text(node.label) }
  })
  const edges = raw.edges.map((value: unknown, i: number) => {
    const edge = record(value), source = aliases.get(String(edge.source)), target = aliases.get(String(edge.target))
    if (!source || !target || edge.type !== 'PUBLISHED_IN') throw new Error('元数据关系不符合接口约定。')
    return { id: `metadata-edge-${i}`, source, target, type: edge.type, evidence: 'A /api/papers/{id}/graph：venue 元数据' }
  })
  if (new Set(nodes.map(n => n.id)).size !== nodes.length) throw new Error('元数据节点 ID 重复。')
  return { nodes, edges, batch_id: range(filters), truncated: false, basis: 'paper_metadata' }
}

export class ApiResearchGateway implements ResearchGateway {
  async getPapers(filters: Filters, signal?: AbortSignal) {
    if (filters.topic || filters.method) throw new Error('主题和方法筛选等待 B 审核与 C 查询接口接入，请重置条件。')
    const query = new URLSearchParams({ page_size: '100' })
    for (const key of ['q', 'year', 'batch_id'] as const) if (filters[key]) query.set(key, filters[key])
    const raw = record(await requestJson<unknown>(`${base}/papers?${query}`, { signal }))
    if (!Array.isArray(raw.items) || typeof raw.total !== 'number') throw new Error('A 论文列表响应格式不正确。')
    return { items: raw.items.map(normalizePaper), total: raw.total, batch_id: range(filters) }
  }
  async getPaper(id: string, signal?: AbortSignal) {
    return normalizePaper(await requestJson(`${base}/papers/${encodeURIComponent(id)}`, { signal }))
  }
  async getGraph(seed: string, hops: number, filters: Filters, signal?: AbortSignal) {
    if (hops !== 1) throw new Error('2 跳扩展等待 C 正式图谱接入。')
    return normalizeMetadataGraph(await requestJson(`${base}/papers/${encodeURIComponent(seed)}/graph`, { signal }), filters)
  }
  async getEntity(id: string, signal?: AbortSignal) {
    if (!id.startsWith('venue:')) throw new Error('该类型实体详情等待 C 接入。')
    const venue = id.slice(6)
    const query = new URLSearchParams({ venue, page_size: '100' })
    const raw = record(await requestJson(`${base}/papers?${query}`, { signal }))
    if (!Array.isArray(raw.items)) throw new Error('会议关联论文响应格式不正确。')
    return { node: { id, type: 'Venue' as const, label: venue }, papers: raw.items.map(normalizePaper), total: Number(raw.total), batch_id: 'A 当前数据库（会议范围）' }
  }
}
export const research: ResearchGateway = new ApiResearchGateway()
