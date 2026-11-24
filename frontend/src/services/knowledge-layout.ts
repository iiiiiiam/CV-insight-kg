import type {GraphNode} from '../types.ts'

export interface Position {x:number;y:number}

// Reserved rectangles include the label below each node, not just its symbol.
const LABEL_WIDTH=150,LABEL_HEIGHT=100
const PRIORITY:Record<string,number>={Paper:0,ResearchDirection:1,Method:2,Task:3,Dataset:4,Topic:5,Author:6,Institution:7,Venue:8}
export function knowledgePositions(nodes:GraphNode[],previous:ReadonlyMap<string,Position>,variant=0):Map<string,Position>{
  const result=new Map<string,Position>()
  // Reserve hidden nodes' slots too, so restoring one does not overlap a new node.
  const occupied:Position[]=[...previous.values()]
  for(const node of nodes){
    const position=previous.get(node.id)
    if(position)result.set(node.id,{...position})
  }
  const pending=nodes.filter(n=>!result.has(n.id)).sort((a,b)=>
    (PRIORITY[a.type]??9)-(PRIORITY[b.type]??9)||a.id.localeCompare(b.id))
  for(const node of pending){
    if(node.type==='Paper'&&!occupied.length){result.set(node.id,{x:0,y:0});occupied.push({x:0,y:0});continue}
    let chosen:Position|undefined
    for(let ring=1;!chosen;ring++){
      const radius=ring*190,slots=Math.max(8,Math.floor(2*Math.PI*radius/170))
      for(let index=0;index<slots;index++){
        const angle=-Math.PI/2+2*Math.PI*index/slots+(variant%12)*Math.PI/6
        const candidate={x:radius*Math.cos(angle),y:radius*Math.sin(angle)}
        if(occupied.every(p=>Math.abs(p.x-candidate.x)>=LABEL_WIDTH||Math.abs(p.y-candidate.y)>=LABEL_HEIGHT)){
          chosen=candidate;break
        }
      }
    }
    result.set(node.id,chosen);occupied.push(chosen)
  }
  return result
}
