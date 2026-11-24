import test from 'node:test'
import assert from 'node:assert/strict'
import {knowledgePositions} from '../src/services/knowledge-layout.ts'
import type {GraphNode} from '../src/types.ts'

const nodes:GraphNode[]=[{id:'p',label:'Paper',type:'Paper'},...Array.from({length:36},(_,i)=>
  ({id:'n'+i,label:'A long author or institution label',type:'Author' as const}))]

test('B layout is deterministic and reserves room for nodes and labels',()=>{
  const positions=knowledgePositions(nodes,new Map())
  assert.deepEqual(positions,knowledgePositions([...nodes].reverse(),new Map()))
  const values=[...positions.values()]
  for(let i=0;i<values.length;i++)for(let j=i+1;j<values.length;j++){
    assert.ok(Math.abs(values[i]!.x-values[j]!.x)>=150||Math.abs(values[i]!.y-values[j]!.y)>=100)
  }
})

test('rename, hide, restore and addition keep existing and manually dragged positions',()=>{
  const original=knowledgePositions(nodes,new Map())
  original.set('n0',{x:1200,y:800})
  const renamed=knowledgePositions(nodes.map(n=>({...n,label:'Renamed'})),original)
  assert.deepEqual(renamed,original)
  const visible=nodes.filter(n=>n.id!=='n1')
  const hidden=knowledgePositions(visible,original)
  for(const node of visible)assert.deepEqual(hidden.get(node.id),original.get(node.id))
  const withExtra=knowledgePositions([...visible,{id:'new',label:'New',type:'Dataset'}],original)
  const saved=new Map([...original,...withExtra])
  const restored=knowledgePositions([...nodes,{id:'new',label:'New',type:'Dataset'}],saved)
  for(const node of nodes)assert.deepEqual(restored.get(node.id),original.get(node.id))
  assert.notDeepEqual(restored.get('new'),restored.get('n1'))
})

test('explicit rearrangement changes placement while normal edits preserve the selected arrangement',()=>{
  const first=knowledgePositions(nodes,new Map(),0)
  const rearranged=knowledgePositions(nodes,new Map(),1)
  assert.deepEqual(first.get('p'),rearranged.get('p'))
  assert.ok(nodes.some(n=>n.type!=='Paper'&&JSON.stringify(first.get(n.id))!==JSON.stringify(rearranged.get(n.id))))
  assert.deepEqual(knowledgePositions(nodes,rearranged,1),rearranged)
  const values=[...rearranged.values()]
  for(let i=0;i<values.length;i++)for(let j=i+1;j<values.length;j++){
    assert.ok(Math.abs(values[i]!.x-values[j]!.x)>=150||Math.abs(values[i]!.y-values[j]!.y)>=100)
  }
})
