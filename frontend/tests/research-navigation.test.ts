import assert from 'node:assert/strict'
import test from 'node:test'
import {researchResultQuery} from '../src/services/research-navigation.ts'

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
