import { requestJson } from './http.ts'

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
export interface KnowledgeOverview {
  dataset_id: string; schema_version: string; rule_version: string; vocabulary_version: string;
  vocabulary_fingerprint: string; entity_count: number; relation_count: number; diagnostic_count: number;
  confirmed_count: number; read_only: true; status: 'pending';
  papers: Array<{openalex_id: string; title: string; year: number; venue: string; entity_count: number; relation_count: number}>;
}
export interface KnowledgeDetail {
  paper: {openalex_id: string; title: string; abstract: string | null; year: number; venue: string; authorships: unknown[]; source_url: string; dataset_id: string};
  result: {paper_id: string; input_fingerprint: string; schema_version: string; rule_version: string;
    vocabulary_version: string; vocabulary_fingerprint: string; entities: Candidate[]; relations: Candidate[]; diagnostics: string[]};
  read_only: true; confirmed_count: 0; scope: 'fixed_snapshot'; notice: string;
}
export function getKnowledgeOverview(signal?: AbortSignal) {
  return requestJson<KnowledgeOverview>('/api/admin/knowledge/snapshot', {signal})
}
export function getKnowledgeDetail(paperId: string, signal?: AbortSignal) {
  return requestJson<KnowledgeDetail>(`/api/admin/knowledge/candidates?${new URLSearchParams({paper_id: paperId})}`, {signal})
}

// B uses Python Unicode code point offsets, not JavaScript UTF-16 offsets.
export function evidenceExcerpt(text: string, evidence: Evidence) {
  const chars = Array.from(text), {start, end} = evidence
  if (!Number.isInteger(start) || !Number.isInteger(end) || start === null || end === null || start < 0 || end < start || end > chars.length) return null
  const quote = chars.slice(start, end).join('')
  if (quote !== evidence.quote) return null
  return {before: chars.slice(0, start).join(''), quote, after: chars.slice(end).join('')}
}
