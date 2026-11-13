import type {EntityContent, RelationContent} from './knowledge.ts'
import type {KnowledgeItem, ReadingKnowledge} from './knowledge-feedback.ts'
import {RELATION_NAMES} from './knowledge-feedback.ts'
import type {EntityType, GraphData} from '../types.ts'

// Personal operations only use browser storage; never implicitly submit feedback.
export interface PersonalKnowledge {
  version: 1
  revision: string
  hidden: string[]
  names: Record<string, string>
  additions: KnowledgeItem[]
}
export interface LocalStoragePort {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}
export const PERSONAL_CHANGE_EVENT = 'knowledge-personal-change'
export function personalKey(paperId: string) { return `research-insight:personal-knowledge:1:${paperId}` }
export function emptyPersonal(revision: string): PersonalKnowledge {
  return {version: 1, revision, hidden: [], names: {}, additions: []}
}
const extraKinds = ['topic', 'method', 'task', 'dataset']
export function readPersonal(storage: LocalStoragePort, paperId: string, revision: string) {
  const body = storage.getItem(personalKey(paperId))
  if (!body) return {draft: emptyPersonal(revision), outdated: false}
  let value: PersonalKnowledge
  try { value = JSON.parse(body) as PersonalKnowledge }
  catch { throw new Error('个人调整记录无法读取，原记录已保留；可恢复默认后重新调整。') }
  if (!value || typeof value !== 'object' || value.version !== 1 || typeof value.revision !== 'string' || !Array.isArray(value.hidden)
    || !value.hidden.every(id => typeof id === 'string') || !value.names || Array.isArray(value.names)
    || typeof value.names !== 'object' || !Object.values(value.names).every(name => typeof name === 'string' && name.trim() && name.length <= 200)
    || !Array.isArray(value.additions)) throw new Error('个人调整记录无法读取，原记录已保留；可恢复默认后重新调整。')
  for (const item of value.additions) {
    const content = item?.content
    if (!item || typeof item.candidate_id !== 'string' || !item.candidate_id.startsWith('personal:')
      || !Array.isArray(item.evidence) || item.evidence.length || !content || typeof content !== 'object' || !('name' in content)
      || !extraKinds.includes(content.kind) || typeof content.name !== 'string' || !content.name.trim()
      || content.name.length > 200 || content.key !== item.candidate_id || content.source_id !== null) {
      throw new Error('个人补充记录无法读取，原记录已保留；可恢复默认后重新调整。')
    }
  }
  return {draft: value.revision === revision ? value : emptyPersonal(revision), outdated: value.revision !== revision}
}
export function savePersonal(storage: LocalStoragePort, paperId: string, draft: PersonalKnowledge) {
  storage.setItem(personalKey(paperId), JSON.stringify(draft))
}
export function resetPersonal(storage: LocalStoragePort, paperId: string) { storage.removeItem(personalKey(paperId)) }
export function personalAddition(kind: string, name: string, id: string): KnowledgeItem {
  name = name.trim()
  if (!extraKinds.includes(kind) || !name || name.length > 200 || !id.startsWith('personal:')) throw new Error('请选择补充类别，并填写不超过 200 字的名称。')
  return {candidate_id: id, content: {key: id, kind, name, source_id: null}, evidence: []}
}
export function applyPersonal(base: ReadingKnowledge, draft: PersonalKnowledge): ReadingKnowledge {
  if (base.revision !== draft.revision) return base
  const hidden = new Set(draft.hidden)
  const entities = [...base.entities, ...draft.additions].filter(item => !hidden.has(item.candidate_id)).map(item => ({
    ...item, content: {...item.content, name: draft.names[item.candidate_id] ?? (item.content as EntityContent).name},
  }))
  const keys = new Set(entities.map(item => (item.content as EntityContent).key))
  const paper = base.entities.find(item => (item.content as EntityContent).kind === 'paper')
  const additions: KnowledgeItem[] = paper ? draft.additions.map(item => ({
    candidate_id: `${item.candidate_id}:relation`,
    content: {source: (paper.content as EntityContent).key, kind: `mentions_${(item.content as EntityContent).kind}`, target: (item.content as EntityContent).key},
    evidence: [],
  })) : []
  const relations = [...base.relations, ...additions].filter(item => {
    const content = item.content as RelationContent
    return !hidden.has(item.candidate_id) && keys.has(content.source) && keys.has(content.target)
  })
  return {...base, entities, relations}
}
export function knowledgeGraph(view: ReadingKnowledge): GraphData {
  const kinds: Record<string, EntityType> = {paper: 'Paper', author: 'Author', institution: 'Institution', venue: 'Venue', topic: 'Topic', method: 'Method', task: 'Task', dataset: 'Dataset'}
  const ids = new Map(view.entities.map(item => [(item.content as EntityContent).key, item.candidate_id]))
  const graph: GraphData = {
    nodes: view.entities.map(item => {const c = item.content as EntityContent; return {id: item.candidate_id, label: c.name, type: kinds[c.kind]!}}),
    edges: view.relations.map(item => {const c = item.content as RelationContent; return {
      id: item.candidate_id, source: ids.get(c.source)!, target: ids.get(c.target)!, type: RELATION_NAMES[c.kind] ?? c.kind,
      evidence: item.evidence.map(e => e.quote).join('\n'),
    }}), truncated: false, batch_id: '',
  }
  const paper = view.entities.find(item => (item.content as EntityContent).kind === 'paper')
  if (paper) {
    for (const direction of view.source_enrichment?.source_classifications ?? []) {
      if (direction.kind !== 'research_direction' || direction.selection === 'fallback' || direction.source_id === 'cv-direction:other') continue
      const id = 'local-direction:' + direction.source_id
      if (graph.nodes.some(n => n.id === id)) continue
      graph.nodes.push({id, label: direction.name, type: 'ResearchDirection'})
      graph.edges.push({id: 'local-direction-link:' + direction.source_id, source: paper.candidate_id,
        target: id, type: '属于研究方向', evidence: ''})
    }
  }
  return graph
}
