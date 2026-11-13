// ResearchDirection is a B-only display node, not a new C storage contract.
export type EntityType = 'Paper' | 'Author' | 'Institution' | 'Topic' | 'Method' | 'Task' | 'Dataset' | 'Venue' | 'ResearchDirection'
export interface Filters {
  q: string; topic: string; method: string; year: string; batch_id: string
  author?: string; author_id?: string; institution?: string; task?: string; dataset?: string; venue?: string
}
export interface Paper {
  id: string; title: string; year: number; topic: string; method: string; task: string;
  dataset: string; venue: string; authors: string[]; institution: string; abstract: string;
  source: string; source_url: string | null; evidence: string; batch_id: string;
  batch_ids?: Array<string | number>; batches?: unknown[];
  openalex_id: string; doi: string; canonical_key: string;
  sources: Array<{name: string; source_id: string; url: string | null; retrieved_at: string}>;
  origin?: 'a' | 'c'; graph_detail?: CDetail;
}
// Effective public snapshots can be automatic or human-corrected.  Evidence
// always points to source text, but an automatic item has no reviewer field.
export interface GraphEvidence {paper_id:string;source_url:string;field:string;quote:string;locator:string;reviewer?:string;reviewed_at?:string}
export interface CNode {id:string;kind:string;type:EntityType;name:string;label:string;title?:string;year?:number;abstract?:string|null;source_id?:string|null;source_url?:string|null;updated_at?:string;missing_fields?:string[];batch_id?:string}
export interface CDetail {node:CNode;related:CNode[];relations:GraphEdge[];truncated:boolean;batch_id:string;batch_provenance?:string}
export interface GraphNode { id: string; label: string; type: EntityType; hop?:number; isNew?:boolean }
export interface GraphEdge { id: string; source: string; target: string; type: string; evidence: string | GraphEvidence[];kind?:string;status?:string;batch_id?:string;isNew?:boolean }
export interface GraphData { nodes: GraphNode[]; edges: GraphEdge[]; truncated: boolean; batch_id: string; basis?: 'paper_metadata'|'published_graph' }
export interface GraphOverview extends GraphData {
  paper_count: number; linked_paper_count: number; hub_count: number; total_hubs: number
}
export interface PaperPage { items: Paper[]; total: number; batch_id: string }
export interface EntityDetail { node: GraphNode; papers: Paper[]; total?: number; batch_id: string;graph_detail?:CDetail }
export interface ResearchGateway {
  getPapers(filters: Filters, signal?: AbortSignal): Promise<PaperPage>;
  getPaper(id: string, signal?: AbortSignal, batchId?:string): Promise<Paper>;
  getGraph(seed: string, hops: number, filters: Filters, signal?: AbortSignal): Promise<GraphData>;
  getEntity(id: string, signal?: AbortSignal, batchId?:string): Promise<EntityDetail>;
}
export interface AdminSession {
  authenticated: true; username: string; role: 'admin'; csrf_token: string; expires_at: string;
}
export const EMPTY_FILTERS: Filters = { q: '', topic: '', method: '', year: '', batch_id: '' }
export const TYPE_LABELS: Record<EntityType, string> = {
  Paper: '论文', Author: '作者', Institution: '机构', Topic: '主题', Method: '方法',
  Task: '任务', Dataset: '数据集', Venue: '会议期刊', ResearchDirection: '研究子方向',
}
export const TYPE_COLORS: Record<EntityType, string> = {
  Paper: '#287c91', Author: '#9072b0', Institution: '#ac718a', Topic: '#d39b43', ResearchDirection: '#b36a24',
  Method: '#198c79', Task: '#778b45', Dataset: '#5583c2', Venue: '#7f8999',
}
