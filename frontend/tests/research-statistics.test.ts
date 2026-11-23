import assert from 'node:assert/strict'
import test from 'node:test'
import {getAuthorProfile,getCoauthors,getInstitutionCollaborations,getInstitutionProfile,getResearchStatistics} from '../src/services/graph.ts'

test('statistics reads latest only when no batch is specified and rejects a mixed batch',async()=>{
  const previousFetch = globalThis.fetch
  const calls:string[] = []
  const empty = {items:[],truncated:false,papers_with_effective_relation:0,papers_without_effective_relation:0}
  const directions = {items:[],truncated:false,basis:'source_classification, not mentions_topic/task'}
  globalThis.fetch = async input=>{
    const query = new URL(String(input),'http://test').searchParams
    calls.push(query.get('batch_id')??'')
    return Response.json({
      batch_id:'effective-current',batch_provenance:'effective_export',paper_count:0,years:[],
      distributions:{topic:empty,method:empty,research_direction:directions},basis:{unit:'distinct_papers',relations:'public_effective'},
    })
  }
  try{
    assert.equal((await getResearchStatistics('')).batch_id,'effective-current')
    assert.equal((await getResearchStatistics('effective-current')).batch_id,'effective-current')
    await assert.rejects(getResearchStatistics('effective-old'),/指定发布批次不一致/)
    assert.deepEqual(calls,['','effective-current','effective-old'])
  }finally{
    globalThis.fetch = previousFetch
  }
})

test('author profile keeps its full batch count across pages and checks author identity',async()=>{
  const previousFetch = globalThis.fetch
  const id = 'author:https://openalex.org/A1'
  const batch = 'effective-snapshot'
  globalThis.fetch = async input=>{
    const url = new URL(String(input),'http://test')
    assert.equal(url.pathname,'/api/research/author-profiles/'+encodeURIComponent(id))
    assert.equal(url.searchParams.get('batch_id'),batch)
    const page = Number(url.searchParams.get('page'))
    return Response.json({
      batch_id:batch,batch_provenance:'effective_export',
      author:{id:page===3?'author:other':id},
      statistics:{batch_id:batch,paper_count:13},
      papers:{items:page===1?Array(12).fill({}):[{}],total:13,page,page_size:12},
      institutions:[],identity:{same_name_other_ids:1},
    })
  }
  try{
    const first = await getAuthorProfile(id,batch,1)
    const second = await getAuthorProfile(id,batch,2)
    assert.deepEqual([first.papers.items.length,second.papers.items.length],[12,1])
    assert.equal(first.papers.total,13)
    assert.equal(second.papers.total,13)
    await assert.rejects(getAuthorProfile(id,batch,3),/指定作者或发布批次不一致/)
  }finally{
    globalThis.fetch = previousFetch
  }
})

test('institution profile pins one batch and applies the institution to statistics and papers',async()=>{
  const previousFetch=globalThis.fetch
  const id='institution:lab-1',batch='effective-institution'
  const scoped:string[]=[]
  const empty={items:[],truncated:false,papers_with_effective_relation:0,papers_without_effective_relation:2}
  globalThis.fetch=async input=>{
    const url=new URL(String(input),'http://test')
    if(url.pathname.startsWith('/api/research/institutions/'))return Response.json({
      batch_id:batch,batch_provenance:'effective_export',
      node:{id,kind:'institution',name:'Vision Lab'},
      related:[{id:'author:1',kind:'author',name:'Alice'},{id:'author:1',kind:'author',name:'Alice'}],
      relations:[],truncated:false,
    })
    assert.equal(url.searchParams.get('batch_id'),batch)
    assert.equal(url.searchParams.get('institution'),id)
    scoped.push(url.pathname)
    if(url.pathname==='/api/research/statistics')return Response.json({
      batch_id:batch,batch_provenance:'effective_export',paper_count:2,years:[{year:2024,paper_count:2}],
      distributions:{topic:empty,method:empty,research_direction:{items:[],truncated:false,basis:'source_classification'}},
      basis:{unit:'distinct_papers',relations:'public_effective'},
    })
    return Response.json({batch_id:batch,batch_provenance:'effective_export',total:2,items:[
      {id:'paper:1',kind:'paper',name:'Paper 1',title:'Paper 1',year:2024,authors:[],author_names:[],venue:'CVPR',citation_count:null},
    ]})
  }
  try{
    const result=await getInstitutionProfile(id,batch,1)
    assert.equal(result.institution.name,'Vision Lab')
    assert.equal(result.papers.total,2)
    assert.equal(result.authors.length,1)
    assert.deepEqual(scoped.sort(),['/api/research/papers','/api/research/statistics'])
  }finally{globalThis.fetch=previousFetch}
})

test('coauthor and institution co-occurrence pages stay pinned to their anchor and revision',async()=>{
  const previousFetch=globalThis.fetch
  const revision='a'.repeat(64),batch='effective-'+revision,calls:string[]=[]
  globalThis.fetch=async input=>{
    const url=new URL(String(input),'http://test');calls.push(url.pathname)
    const isAuthor=url.pathname.endsWith('/coauthors')
    assert.equal(url.searchParams.get('batch_id'),batch)
    assert.equal(url.searchParams.get('page'),'2')
    assert.equal(url.searchParams.get('page_size'),'8')
    const anchorId=isAuthor?'author:1':'institution:1'
    assert.equal(url.searchParams.get(isAuthor?'anchor_id':'institution_id'),anchorId)
    return Response.json({batch_id:batch,batch_provenance:'effective_export',revision,
      anchor:{id:anchorId,source_id:null,name:'Anchor',identity_state:'resolved',paper_count:3},
      items:[{id:isAuthor?'author:2':'institution:2',source_id:null,name:'Partner',identity_state:'resolved',paper_count:2,
        shared_papers:[{id:'paper:1',title:'Shared',year:2024,source_id:'W1',source_url:null,sources:[]}],shared_papers_truncated:false}],
      total:1,page:2,page_size:8,truncated:false,shared_paper_limit:8,basis:'shared_paper_evidence'})
  }
  try{
    assert.equal((await getCoauthors('author:1',batch,2)).items[0]?.name,'Partner')
    assert.equal((await getInstitutionCollaborations('institution:1',batch,2)).items[0]?.paper_count,2)
    assert.deepEqual(calls,['/api/research/coauthors','/api/research/institution-collaborations'])
  }finally{globalThis.fetch=previousFetch}
})
