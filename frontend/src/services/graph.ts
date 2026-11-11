import type {CDetail,CNode,EntityDetail,EntityType,Filters,GraphData,GraphOverview,Paper,ResearchGateway} from '../types.ts'
import {requestJson} from './http.ts'
import {safeSourceUrl} from './research.ts'

function batchQuery(batch?:string){return batch?`?${new URLSearchParams({batch_id:batch})}`:''}
function checked<T extends {batch_id:string;batch_provenance?:string}>(data:T):T{
  if(!data.batch_id||!['reviewed_export','effective_export'].includes(data.batch_provenance??''))throw new Error('研究数据没有通过公共知识发布批次校验。')
  return data
}
export function normalizeCNode(value:CNode):CNode{
  const kinds:Record<string,EntityType>={paper:'Paper',author:'Author',institution:'Institution',topic:'Topic',method:'Method',task:'Task',dataset:'Dataset',venue:'Venue'}
  if(!value.id||!kinds[value.kind]||typeof value.name!=='string')throw new Error('C 返回的实体格式不正确。')
  return {...value,type:kinds[value.kind]!,label:value.name}
}
export function normalizeCPaper(node:CNode,batch:string,detail?:CDetail):Paper{
  const n=normalizeCNode(node),related=detail?.related??[]
  const names=(kind:string)=>related.filter(x=>x.kind===kind).map(x=>x.name)
  const openalex=[n.source_id,n.source_url].find(x=>typeof x==='string'&&/^https:\/\/openalex\.org\/W\d+$/.test(x))??''
  return {id:n.id,title:n.title??n.name,year:n.year??0,abstract:n.abstract??'该批次未提供摘要。',authors:names('author'),
    topic:names('topic').join('、')||'图谱详情中查看',method:names('method').join('、')||'图谱详情中查看',
    task:names('task').join('、')||'图谱详情中查看',dataset:names('dataset').join('、')||'图谱详情中查看',
    institution:'按论文上下文查看关联证据',venue:names('venue').join('、')||'会议见图谱详情',
    source:'C 已发布公共图谱',source_url:safeSourceUrl(n.source_url),evidence:'当前内容来自 B 的有效公共知识快照及已生效修正，并已发布到 C。提及不等于使用或验证。',
    batch_id:batch,batch_ids:[batch],batches:[],openalex_id:openalex,doi:'',canonical_key:n.id,sources:[],origin:'c',graph_detail:detail}
}
export class CResearchGateway implements ResearchGateway{
  async getPapers(filters:Filters,signal?:AbortSignal,page=1,pageSize=100){
    const query=new URLSearchParams({page:String(page),page_size:String(pageSize),sort:'year_desc'})
    for(const [key,value] of Object.entries(filters))if(value)query.set(key,value)
    const result=checked(await requestJson<{items:CNode[];total:number;batch_id:string;batch_provenance:string}>(`/api/research/papers?${query}`,{signal}))
    if(!Array.isArray(result.items))throw new Error('C 论文列表响应格式不正确。')
    return {items:result.items.map(n=>normalizeCPaper(n,result.batch_id)),total:result.total,batch_id:result.batch_id}
  }
  async getPaper(id:string,signal?:AbortSignal,batchId?:string){
    const detail=await this.getDetail(id,signal,batchId,'papers')
    return normalizeCPaper(detail.node,detail.batch_id,detail)
  }
  async getDetail(id:string,signal?:AbortSignal,batchId?:string,resource='entities'){
    const result=checked(await requestJson<CDetail>(`/api/research/${resource}/${encodeURIComponent(id)}${batchQuery(batchId)}`,{signal}))
    result.node=normalizeCNode(result.node);result.related=result.related.map(normalizeCNode)
    if(batchId&&result.batch_id!==batchId)throw new Error('C 详情与当前批次不一致。')
    return result
  }
  async getGraph(seed:string,hops:number,filters:Filters,signal?:AbortSignal,limit=100):Promise<GraphData>{
    const query=new URLSearchParams({seed,hops:String(hops),limit:String(limit)})
    for(const key of ['q','topic','method','year','batch_id'] as const)if(filters[key])query.set(key,filters[key])
    const result=checked(await requestJson<GraphData&{batch_provenance:string}>(`/api/research/graph?${query}`,{signal}))
    if(!Array.isArray(result.nodes)||!Array.isArray(result.edges))throw new Error('C 子图响应格式不正确。')
    const ids=new Set(result.nodes.map(n=>n.id))
    if(ids.size!==result.nodes.length||result.edges.some(e=>!ids.has(e.source)||!ids.has(e.target)||!Array.isArray(e.evidence)))throw new Error('C 子图节点、端点或证据格式不正确。')
    if(filters.batch_id&&filters.batch_id!==result.batch_id)throw new Error('C 子图批次不一致。')
    return {...result,basis:'published_graph'}
  }
  async getEntity(id:string,signal?:AbortSignal,batchId?:string):Promise<EntityDetail>{
    const detail=await this.getDetail(id,signal,batchId)
    return {node:detail.node,papers:detail.related.filter(n=>n.kind==='paper').map(n=>normalizeCPaper(n,detail.batch_id)),batch_id:detail.batch_id,graph_detail:detail}
  }
}
export const graphResearch=new CResearchGateway()
export async function searchGraphEntities(q:string,kind:string,batch:string,signal?:AbortSignal,page=1,pageSize=100){
  const query=new URLSearchParams({q,limit:String(pageSize),page:String(page)})
  if(kind)query.set('kind',kind)
  if(batch)query.set('batch_id',batch)
  const result=checked(await requestJson<{items:CNode[];total:number;truncated:boolean;batch_id:string;batch_provenance:string}>(`/api/research/entities?${query}`,{signal}))
  return {...result,items:result.items.map(normalizeCNode)}
}
export async function getGraphOverview(batch:string,signal?:AbortSignal){
  return checked(await requestJson<GraphOverview & {batch_provenance:string}>(`/api/research/graph-overview${batchQuery(batch)}`,{signal}))
}

interface ResearchDistribution {
  items:Array<{id:string;name:string;paper_count:number;share:number}>
  truncated:boolean
  papers_with_effective_relation:number
  papers_without_effective_relation:number
}
export interface ResearchStatistics {
  batch_id:string
  batch_provenance:string
  paper_count:number
  years:Array<{year:number;paper_count:number}>
  distributions:Record<'topic'|'method',ResearchDistribution>
  basis:{unit:string;relations:string}
}
export async function getResearchStatistics(batch:string,signal?:AbortSignal){
  const query = new URLSearchParams({limit:'12'})
  if(batch)query.set('batch_id',batch)
  const result = checked(await requestJson<ResearchStatistics>(`/api/research/statistics?${query}`,{signal}))
  if(batch&&result.batch_id!==batch)throw new Error('统计结果与指定发布批次不一致。')
  if(result.basis?.unit!=='distinct_papers'||!Array.isArray(result.years)
    ||!Array.isArray(result.distributions?.topic?.items)||!Array.isArray(result.distributions?.method?.items)){
    throw new Error('C 返回的统计格式或计数口径不符合预期。')
  }
  return result
}

export interface AuthorProfile {
  batch_id:string
  batch_provenance:string
  author:CNode
  statistics:Omit<ResearchStatistics,'batch_provenance'>
  papers:{items:CNode[];total:number;page:number;page_size:number}
  institutions:Array<{id:string;name:string;paper_ids:string[]}>
  identity:{same_name_other_ids:number}
}
export async function getAuthorProfile(id:string,batch:string,page:number,signal?:AbortSignal){
  const query = new URLSearchParams({batch_id:batch,page:String(page),page_size:'12',limit:'8'})
  const profile = checked(await requestJson<AuthorProfile>(
    `/api/research/author-profiles/${encodeURIComponent(id)}?${query}`,{signal},
  ))
  if(profile.batch_id!==batch||profile.statistics?.batch_id!==batch||profile.author?.id!==id){
    throw new Error('作者画像与指定作者或发布批次不一致。')
  }
  if(profile.papers?.page!==page||profile.papers.total!==profile.statistics.paper_count
    ||!Array.isArray(profile.papers.items)||!Array.isArray(profile.institutions)){
    throw new Error('C 返回的作者画像统计与论文清单不一致。')
  }
  return profile
}
