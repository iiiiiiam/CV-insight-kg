import fs from 'node:fs';
import assert from 'node:assert/strict';
const code=fs.readFileSync('src/graph_query/graph-view.js');
const {selectVisible,layout}=await import('data:text/javascript;base64,'+code.toString('base64'));
const data={nodes:Array.from({length:100},(_,i)=>({id:String(i),kind:i%2?'author':'paper'})),edges:Array.from({length:99},(_,i)=>({source:'0',target:String(i+1),kind:'has_author'}))};
const v=selectVisible(data,'99');assert.equal(v.nodes.length,60);assert.ok(v.nodes.some(n=>n.id==='99'));assert.equal(v.limited,true);assert.ok(v.edges.every(e=>v.nodes.some(n=>n.id===e.source)&&v.nodes.some(n=>n.id===e.target)));
const filtered=selectVisible(data,'0',new Set(['author']));assert.ok(filtered.nodes.every(n=>n.kind==='paper'));assert.equal(filtered.edges.length,49);
const pos=layout(v.nodes,v.edges);assert.equal(pos.size,60);assert.ok([...pos.values()].every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));assert.deepEqual(selectVisible({nodes:[],edges:[]},'x').nodes,[]);assert.equal(layout([{id:'solo'}],[]).size,1);
console.log('graph-view: 7 layout/filter/limit/empty checks passed');
