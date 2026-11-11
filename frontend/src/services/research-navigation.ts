import type {LocationQuery} from 'vue-router'

const searchKeys = [
  'tab','q','kind','page','batch_id','year','topic','method',
  'author','author_id','institution','task','dataset','venue',
] as const

export function researchResultQuery(query:LocationQuery):Record<string,string>{
  const result:Record<string,string> = {}
  for(const key of searchKeys){
    const value = query[key]
    if(typeof value==='string'&&value)result[key] = value
  }
  return result
}
