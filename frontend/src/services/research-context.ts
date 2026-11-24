import type {LocationQuery,LocationQueryRaw} from 'vue-router'

/**
 * Keeps a research journey in one URL-safe context.  These values only describe
 * the user's current view; they are never sent as a write request to A/B/C.
 */
export const RESEARCH_CONTEXT_KEYS=['q','topic','method','year','batch_id','seed','selected'] as const

export function keepResearchContext(query:LocationQuery):LocationQueryRaw{
  const result:LocationQueryRaw={}
  for(const key of RESEARCH_CONTEXT_KEYS){
    const value=query[key]
    if(typeof value==='string'&&value)result[key]=value
  }
  return result
}

export function researchTarget(path:string,query:LocationQuery,extra:LocationQueryRaw={}):{path:string;query:LocationQueryRaw}{
  return {path,query:{...keepResearchContext(query),...extra}}
}
