import type {LocationQuery,LocationQueryRaw} from 'vue-router'

const searchKeys = [
  'tab','q','kind','page','batch_id','year','topic','method',
  'author','author_id','institution','task','dataset','venue','direction','sort','page_size',
] as const
const multiKeys=new Set(['author','author_id','institution','topic','method','task','dataset','venue','direction','year'])

export function researchResultQuery(query:LocationQuery):LocationQueryRaw{
  const result:LocationQueryRaw = {}
  for(const key of searchKeys){
    const value = query[key]
    if(typeof value==='string'&&value)result[key] = value
    else if(Array.isArray(value)&&multiKeys.has(key)){
      const values=value.filter((item):item is string=>typeof item==='string'&&!!item)
      if(values.length)result[key]=values
    }
  }
  return result
}

export function knowledgePaperIdFromGraphId(value:string):string{
  const raw=value.startsWith('paper:')?value.slice(6):value
  const full=raw.match(/^https?:\/\/openalex\.org\/(W\d+)\/?$/i)
  if(full)return `https://openalex.org/${full[1]}`
  const short=raw.match(/^W\d+$/i)
  return short?`https://openalex.org/${short[0].toUpperCase()}`:''
}

export function safeResearchReturn(value:unknown):string|null{
  return typeof value==='string'&&/^\/research\/papers(?:\?|$)/.test(value)?value:null
}
