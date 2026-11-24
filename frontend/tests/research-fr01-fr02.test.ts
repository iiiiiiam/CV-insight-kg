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
        authors:[{id:'author:1',source_id:'A1',name:'Alice'},{id:null,source_id:null,name:'Bob'}],author_names:['Alice','Bob'],
        venue:'CVPR',citation_count:null,openalex_id:'https://openalex.org/W1',source_updated_at:null,
        knowledge_exported_at:'2026-11-11T00:00:00Z',graph_published_at:'2026-11-12T00:00:00Z',data_revision:'a'.repeat(64)}],
    }),{headers:{'Content-Type':'application/json'}})
  }
  try{
    const result=await graphResearch.getPapers({...EMPTY_FILTERS,topic:['Vision','Generation'],
      author:['Alice','Bob'],author_id:['author:1','author:2'],institution:['Lab'],method:'Diffusion',
      year:['2023','2024'],direction:['目标检测','cv-direction:object-detection'],sort:'title'},undefined,2,20)
    const query=new URL(called,'http://localhost').searchParams
    assert.deepEqual(query.getAll('topic'),['Vision','Generation'])
    assert.deepEqual(query.getAll('author'),['Alice','Bob'])
    assert.equal(query.get('institution'),'Lab')
    assert.equal(query.get('method'),'Diffusion')
    assert.deepEqual(query.getAll('author_id'),['author:1','author:2'])
    assert.deepEqual(query.getAll('year'),['2023','2024'])
    assert.deepEqual(query.getAll('direction'),['目标检测','cv-direction:object-detection'])
    assert.equal(query.get('sort'),'title')
    assert.equal(query.get('page'),'2')
    assert.deepEqual(result.items[0]!.authors,['Alice','Bob'])
    assert.equal(result.items[0]!.venue,'CVPR')
    assert.equal(result.items[0]!.citation_count,null)
    assert.equal(result.items[0]!.openalex_id,'https://openalex.org/W1')
    assert.equal(result.items[0]!.source_updated_at,null)
    assert.equal(result.items[0]!.data_revision,'a'.repeat(64))
  }finally{globalThis.fetch=original}
})
