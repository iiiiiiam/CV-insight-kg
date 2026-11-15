import assert from 'node:assert/strict'
import test from 'node:test'
import {knowledgePaperIdFromGraphId,researchResultQuery,safeResearchReturn} from '../src/services/research-navigation.ts'

test('returning from detail or graph preserves all committed research filters and pagination',()=>{
  const filters = {
    tab:'papers',q:'diffusion',page:'3',batch_id:'effective-123',year:'2024',
    topic:'Vision',method:'Diffusion',author:'Lee',author_id:'author:1',
    institution:'Lab',task:'Generation',dataset:'COCO',venue:'CVPR',
  }
  assert.deepEqual(researchResultQuery({
    ...filters,detail:'paper:1',seed:'author:1',seed_label:'Lee',source:'c',
  }),filters)
})

test('an entity search keeps its type and keyword when closing a result view',()=>{
  const filters = {tab:'entities',kind:'institution',q:'University',page:'2'}
  assert.deepEqual(researchResultQuery({...filters,detail:'institution:1'}),filters)
  assert.deepEqual(researchResultQuery({q:['one','two'],page:'',detail:'paper:1'}),{})
})

test('FR01 keeps repeated values only for supported multi-value dimensions',()=>{
  assert.deepEqual(researchResultQuery({
    tab:'papers',topic:['Vision','Generation'],author:['author:1','author:2'],
    method:'Diffusion',q:['invalid','query'],page_size:'100',sort:'title',
  }),{
    tab:'papers',topic:['Vision','Generation'],author:['author:1','author:2'],
    method:'Diffusion',page_size:'100',sort:'title',
  })
})

test('C paper IDs map to the single B knowledge page and research returns stay internal',()=>{
  assert.equal(knowledgePaperIdFromGraphId('paper:https://openalex.org/W4402754006'),'https://openalex.org/W4402754006')
  assert.equal(knowledgePaperIdFromGraphId('w123'),'https://openalex.org/W123')
  assert.equal(knowledgePaperIdFromGraphId('paper:local-only'),'')
  assert.equal(safeResearchReturn('/research/papers?topic=Vision&seed=paper%3A1'),'/research/papers?topic=Vision&seed=paper%3A1')
  assert.equal(safeResearchReturn('/research/papers-evil'),null)
  assert.equal(safeResearchReturn('https://example.com'),null)
})
