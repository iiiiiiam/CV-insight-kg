import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import test from 'node:test'
import {ApiResearchGateway, normalizeMetadataGraph, normalizePaper, safeSourceUrl} from '../src/services/research.ts'
import {evidenceExcerpt} from '../src/services/knowledge.ts'
import type {Evidence} from '../src/services/knowledge.ts'
import {EMPTY_FILTERS} from '../src/types.ts'

// Fixtures come from A's actual fixed sample; they are never bundled in the UI.
const manifest=JSON.parse(readFileSync(new URL('../../examples/week1_baseline.json',import.meta.url),'utf8'))
const work=JSON.parse(readFileSync(new URL('../../examples/cvpr_2024_seed.jsonl',import.meta.url),'utf8').split(/\r?\n/)[0]!)
const paper={id:1,title:work.display_name,year:work.publication_year,venue:manifest.venue,
  authors:work.authorships.map((a:any)=>a.author.display_name),openalex_id:work.id,doi:work.doi,
  source_url:manifest.papers[0].source_url,batch_ids:[1],sources:[{name:'openalex',source_id:work.id,url:work.id,retrieved_at:'2026-10-30'}]}
const graph={basis:'paper_metadata',nodes:[{id:'paper:1',type:'Paper',label:paper.title,paper_id:1},{id:'venue:CVPR',type:'Venue',label:'CVPR'}],edges:[{source:'paper:1',target:'venue:CVPR',type:'PUBLISHED_IN'}]}

test('real paper keeps stable identity and source, without inventing reviewed labels',()=>{
  const result=normalizePaper(paper)
  assert.equal(result.openalex_id,work.id)
  assert.equal(result.title,work.display_name)
  assert.deepEqual(result.authors,paper.authors)
  assert.equal(result.sources[0]!.source_id,work.id)
  assert.equal(result.method,'待 B 审核')
  assert.equal(result.topic,'待 B 审核')
  assert.deepEqual(result.batch_ids,[1])
})
test('unsafe source URLs are not turned into links',()=>{
  assert.equal(safeSourceUrl('javascript:alert(1)'),null)
  assert.equal(safeSourceUrl('data:text/html,bad'),null)
  assert.equal(safeSourceUrl(work.id),work.id)
})
test('A paper graph ID maps to list ID and preserves actual relation',()=>{
  const result=normalizeMetadataGraph(graph,EMPTY_FILTERS)
  assert.equal(result.nodes[0]!.id,'1')
  assert.equal(result.edges[0]!.source,'1')
  assert.equal(result.edges[0]!.target,'venue:CVPR')
  assert.equal(result.edges[0]!.type,'PUBLISHED_IN')
  assert.equal(result.nodes.length,2)
  assert.equal(result.edges.length,1)
})
test('dangling graph edges and unsupported semantic relations fail explicitly',()=>{
  assert.throws(()=>normalizeMetadataGraph({...graph,edges:[{source:'missing',target:'venue:CVPR',type:'PUBLISHED_IN'}]},EMPTY_FILTERS))
  assert.throws(()=>normalizeMetadataGraph({...graph,edges:[{source:'paper:1',target:'venue:CVPR',type:'USES_METHOD'}]},EMPTY_FILTERS))
})
test('Python Unicode evidence offsets highlight the exact code points',()=>{
  const proof={start:2,end:4,quote:'检测'} as Evidence
  assert.deepEqual(evidenceExcerpt('A😀检测B',proof),{before:'A😀',quote:'检测',after:'B'})
  assert.equal(evidenceExcerpt('A😀检测B',{...proof,quote:'错误'}),null)
  assert.equal(evidenceExcerpt('A😀检测B',{...proof,start:-1}),null)
})
test('unsupported topic filter and two-hop requests never fabricate responses',async()=>{
  const gateway=new ApiResearchGateway()
  await assert.rejects(gateway.getPapers({...EMPTY_FILTERS,topic:'detection'}),/等待 B/)
  await assert.rejects(gateway.getGraph('1',2,EMPTY_FILTERS),/等待 C/)
})
test('list, metadata graph and venue detail use actual A API contracts',async()=>{
  const original=globalThis.fetch,calls:string[]=[]
  globalThis.fetch=async(input)=>{
    const url=String(input);calls.push(url)
    return new Response(JSON.stringify(url.includes('/graph')?graph:{items:[paper],total:1}),{headers:{'Content-Type':'application/json'}})
  }
  try{
    const gateway=new ApiResearchGateway(),filters={...EMPTY_FILTERS,q:'DETR',year:'2024',batch_id:'1'}
    const page=await gateway.getPapers(filters)
    const metadata=await gateway.getGraph('1',1,filters)
    assert.equal(page.batch_id,metadata.batch_id)
    assert.equal(page.items[0]!.id,metadata.nodes[0]!.id)
    const query=new URL(calls[0]!,'http://localhost').searchParams
    assert.equal(query.get('q'),'DETR');assert.equal(query.get('year'),'2024');assert.equal(query.get('batch_id'),'1')
    assert.equal((await gateway.getEntity('venue:CVPR')).papers[0]!.openalex_id,work.id)
  }finally{globalThis.fetch=original}
})
test('an upstream error is surfaced without fallback records',async()=>{
  const original=globalThis.fetch
  globalThis.fetch=async()=>new Response(JSON.stringify({error:{message:'A 服务不可用'}}),{status:502})
  try{await assert.rejects(new ApiResearchGateway().getPapers(EMPTY_FILTERS),/A 服务不可用/)}
  finally{globalThis.fetch=original}
})
