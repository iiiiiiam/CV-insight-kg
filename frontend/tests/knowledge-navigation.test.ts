import assert from 'node:assert/strict'
import test from 'node:test'
import {filterPaperDirections,filterPaperTitles,LAST_KNOWLEDGE_PAPER,readLastPaper,rememberPaper,resolveReadingPaper} from '../src/services/knowledge-navigation.ts'

test('direction and title combine over the complete input without duplicating multi-direction papers',()=>{
  const rows=[{paper_id:'1',title:'Image Generation',research_directions:[{id:'generation',name:'生成'},{id:'3d',name:'三维'}]},
    {paper_id:'2',title:'Video Generation',research_directions:[{id:'generation',name:'生成'}]},
    {paper_id:'3',title:'Other',research_directions:[{id:'other',name:'其他'}]}]
  assert.deepEqual(filterPaperDirections(rows,'image','generation').map(p=>p.paper_id),['1'])
  assert.equal(filterPaperDirections(rows,'','generation').length,2)
  assert.equal(filterPaperDirections(rows,'','').length,3)
  assert.equal(filterPaperDirections(rows,'','unknown').length,0)
  assert.equal(filterPaperDirections(rows,'','other')[0]?.paper_id,'3')
})

const papers=[{paper_id:'W1',title:'DETR for Object Detection'},{paper_id:'W2',title:'Stable Diffusion for Panorama Generation'},{paper_id:'W3',title:'Video Diffusion Models'}]

test('title search supports case-insensitive multiple words and full-width input',()=>{
  assert.deepEqual(filterPaperTitles(papers,'  DIFFUSION  video ').map(p=>p.paper_id),['W3'])
  assert.deepEqual(filterPaperTitles(papers,'ＤＥＴＲ').map(p=>p.paper_id),['W1'])
  assert.deepEqual(filterPaperTitles(papers,'   '),papers)
})
test('a title search with no match does not change paper records or the reading selection',()=>{
  const original=JSON.stringify(papers)
  assert.deepEqual(filterPaperTitles(papers,'nonexistent'),[])
  assert.equal(JSON.stringify(papers),original)
  assert.equal(resolveReadingPaper(papers,'W2','W3'),'W2')
})
test('explicit paper links win over history while invalid or absent links restore valid history',()=>{
  assert.equal(resolveReadingPaper(papers,'W2','W3'),'W2')
  assert.equal(resolveReadingPaper(papers,'','W3'),'W3')
  assert.equal(resolveReadingPaper(papers,'removed','W3'),'W3')
  assert.equal(resolveReadingPaper(papers,'','removed'),'W1')
  assert.equal(resolveReadingPaper([],'W2','W3'),'')
})
test('remembering a paper survives a new page instance without touching personal edits',()=>{
  const values=new Map([['personal-edit','keep']])
  const storage={getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>{values.set(k,v)}}
  assert.equal(rememberPaper(storage,'W3'),true)
  assert.equal(values.get(LAST_KNOWLEDGE_PAPER),'W3')
  assert.equal(resolveReadingPaper(papers,'',readLastPaper(storage)),'W3')
  assert.equal(values.get('personal-edit'),'keep')
})
test('blocked browser storage does not prevent opening a linked paper',()=>{
  const blocked={getItem:()=>{throw new Error('blocked')},setItem:()=>{throw new Error('blocked')}}
  assert.equal(readLastPaper(blocked),null)
  assert.equal(rememberPaper(blocked,'W2'),false)
  assert.equal(resolveReadingPaper(papers,'W2',readLastPaper(blocked)),'W2')
})
