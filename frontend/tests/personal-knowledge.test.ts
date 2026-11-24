import assert from 'node:assert/strict'
import test from 'node:test'
import {applyPersonal,emptyPersonal,knowledgeGraph,personalAddition,personalKey,readPersonal,resetPersonal,savePersonal} from '../src/services/personal-knowledge.ts'
import type {LocalStoragePort} from '../src/services/personal-knowledge.ts'
import type {ReadingKnowledge} from '../src/services/knowledge-feedback.ts'

function fixture(): ReadingKnowledge {
  return {paper:{openalex_id:'W1',title:'Paper',abstract:'LVIS',year:2024,venue:'CVPR',source_url:''},revision:'r1',vocabulary_version:'v1',
    entities:[{candidate_id:'p',content:{key:'paper:1',kind:'paper',name:'Paper',source_id:null},evidence:[]},
      {candidate_id:'d',content:{key:'dataset:1',kind:'dataset',name:'LVIS',source_id:null},evidence:[]}],
    relations:[{candidate_id:'r',content:{source:'paper:1',kind:'mentions_dataset',target:'dataset:1'},evidence:[]}]}
}
function memory(): LocalStoragePort {
  const values=new Map<string,string>()
  return {getItem:key=>values.get(key)??null,setItem:(key,value)=>{values.set(key,value)},removeItem:key=>{values.delete(key)}}
}

test('B direction display nodes stay distinct from tasks and never mutate public items',()=>{
  const base=fixture()
  base.source_enrichment={source_classifications:[
    {kind:'research_direction',name:'图像分割',source:'b_rules',source_url:'',source_id:'cv-direction:segmentation',selection:'primary'},
    {kind:'research_direction',name:'其他',source:'b_rules',source_url:'',source_id:'cv-direction:other',selection:'fallback'},
  ],source_records:[],accepted_signals:[],added_entities:[]}
  base.entities.push({candidate_id:'task',content:{key:'task:1',kind:'task',name:'图像分割',source_id:null},evidence:[]})
  const before=JSON.stringify(base),graph=knowledgeGraph(base)
  const direction=graph.nodes.find(n=>n.type==='ResearchDirection')!
  assert.equal(direction.label,'图像分割')
  assert.equal(graph.nodes.find(n=>n.id==='task')?.type,'Task')
  assert.equal(graph.nodes.filter(n=>n.type==='ResearchDirection').length,1)
  assert.equal(graph.edges.find(e=>e.target===direction.id)?.type,'属于研究方向')
  assert.equal(JSON.stringify(base),before)
  const hidden=applyPersonal(base,{...emptyPersonal(base.revision),hidden:['p']})
  assert.equal(knowledgeGraph(hidden).nodes.some(n=>n.type==='ResearchDirection'),false)
})

test('hiding an object removes incident edges in both list and graph, preserving public data',()=>{
  const base=fixture(),before=JSON.stringify(base),draft={...emptyPersonal(base.revision),hidden:['d']}
  const result=applyPersonal(base,draft),graph=knowledgeGraph(result)
  assert.deepEqual(result.entities.map(item=>item.candidate_id),['p'])
  assert.equal(result.relations.length,0);assert.equal(graph.edges.length,0)
  assert.deepEqual(graph.nodes.map(node=>node.id),['p'])
  assert.equal(JSON.stringify(base),before)
  assert.equal(applyPersonal(base,{...draft,hidden:[]}).relations.length,1)
})
test('hiding only a relation keeps both objects and can be undone',()=>{
  const base=fixture(),draft={...emptyPersonal(base.revision),hidden:['r']}
  assert.equal(applyPersonal(base,draft).entities.length,2)
  assert.equal(knowledgeGraph(applyPersonal(base,draft)).edges.length,0)
  assert.equal(knowledgeGraph(applyPersonal(base,emptyPersonal(base.revision))).edges.length,1)
})
test('personal names and additions appear in graph without inventing source evidence',()=>{
  const base=fixture(),extra=personalAddition('method',' RepVL-PAN ','personal:test')
  const draft={...emptyPersonal(base.revision),names:{d:'My LVIS'},additions:[extra]}
  const result=applyPersonal(base,draft),graph=knowledgeGraph(result)
  assert.equal(graph.nodes.find(node=>node.id==='d')?.label,'My LVIS')
  assert.equal(graph.nodes.find(node=>node.id==='personal:test')?.label,'RepVL-PAN')
  assert.equal(graph.edges.find(edge=>edge.id==='personal:test:relation')?.source,'p')
  assert.deepEqual(result.entities.find(item=>item.candidate_id==='personal:test')?.evidence,[])
  assert.equal(graph.edges.find(edge=>edge.id==='personal:test:relation')?.evidence,'')
  assert.equal('reviewer' in extra,false)
  assert.throws(()=>personalAddition('venue','CVPR','personal:x'))
  assert.throws(()=>personalAddition('method','  ','personal:x'))
})
test('local changes persist per paper and reset without sending any network request',()=>{
  const storage=memory(),previous=globalThis.fetch
  globalThis.fetch=()=>{throw new Error('Local editing must not call the backend')}
  try{
    const draft={...emptyPersonal('r1'),hidden:['r'],names:{d:'My LVIS'},additions:[personalAddition('task','Segmentation','personal:task')]}
    savePersonal(storage,'W1',draft)
    assert.deepEqual(readPersonal(storage,'W1','r1').draft,draft)
    assert.deepEqual(readPersonal(storage,'W2','r1').draft,emptyPersonal('r1'))
    assert.equal(applyPersonal(fixture(),readPersonal(storage,'W1','r1').draft).relations.length,1)
    resetPersonal(storage,'W1')
    assert.equal(storage.getItem(personalKey('W1')),null)
    assert.equal(applyPersonal(fixture(),readPersonal(storage,'W1','r1').draft).relations.length,1)
  }finally{globalThis.fetch=previous}
})
test('new public revisions suspend older edits and preserve original saved records',()=>{
  const storage=memory(),draft={...emptyPersonal('r1'),hidden:['d']}
  savePersonal(storage,'W1',draft)
  const saved=storage.getItem(personalKey('W1')),result=readPersonal(storage,'W1','r2')
  assert.equal(result.outdated,true);assert.deepEqual(result.draft,emptyPersonal('r2'))
  assert.equal(storage.getItem(personalKey('W1')),saved)
  const base={...fixture(),revision:'r2'}
  assert.equal(applyPersonal(base,draft),base)
})
test('corrupt local records and storage failures do not silently overwrite saved data',()=>{
  const storage=memory();storage.setItem(personalKey('W1'),'{broken')
  assert.throws(()=>readPersonal(storage,'W1','r1'))
  assert.equal(storage.getItem(personalKey('W1')),'{broken')
  storage.setItem(personalKey('W1'),JSON.stringify({...emptyPersonal('r1'),additions:[{candidate_id:'fake'}]}))
  assert.throws(()=>readPersonal(storage,'W1','r1'))
  const failing={...storage,setItem:()=>{throw new Error('quota')}}
  assert.throws(()=>savePersonal(failing,'W1',emptyPersonal('r1')),/quota/)
})
