import assert from 'node:assert/strict'
import test from 'node:test'
import {graphResearch} from '../src/services/graph.ts'
import {EMPTY_FILTERS} from '../src/types.ts'

test('FR01 sends repeated same-dimension values and keeps cross-dimension filters',async()=>{
  const original=globalThis.fetch
  let called=''
  globalThis.fetch=async input=>{
    called=String(input)
    return new Response(JSON.stringify({
      batch_id:'effective-test',batch_provenance:'effective_export',total:1,
      items:[{id:'paper:1',kind:'paper',name:'A paper',title:'A paper',year:2024,
        authors:['Alice','Bob'],venue:'CVPR',citation_count:null,updated_at:'2026-11-11T00:00:00Z'}],
    }),{headers:{'Content-Type':'application/json'}})
  }
  try{
    const result=await graphResearch.getPapers({...EMPTY_FILTERS,topic:['Vision','Generation'],
      author:['Alice','Bob'],institution:['Lab'],method:'Diffusion',year:'2024',sort:'title'},undefined,2,20)
    const query=new URL(called,'http://localhost').searchParams
    assert.deepEqual(query.getAll('topic'),['Vision','Generation'])
    assert.deepEqual(query.getAll('author'),['Alice','Bob'])
    assert.equal(query.get('institution'),'Lab')
    assert.equal(query.get('method'),'Diffusion')
    assert.equal(query.get('sort'),'title')
    assert.equal(query.get('page'),'2')
    assert.deepEqual(result.items[0]!.authors,['Alice','Bob'])
    assert.equal(result.items[0]!.venue,'CVPR')
    assert.equal(result.items[0]!.citation_count,null)
  }finally{globalThis.fetch=original}
})
