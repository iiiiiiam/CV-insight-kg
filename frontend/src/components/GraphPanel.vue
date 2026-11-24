<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import cytoscape from 'cytoscape'
import type {GraphData,GraphNode,EntityType} from '../types.ts'
import {TYPE_COLORS,TYPE_LABELS} from '../types.ts'
import {RELATION_NAMES} from '../services/knowledge-feedback.ts'
import AppIcon from './AppIcon.vue'
import {knowledgePositions} from '../services/knowledge-layout.ts'

const props=defineProps<{graph:GraphData;selectedId:string;overview?:boolean;rootId?:string;stableKnowledge?:boolean;layoutKey?:string}>()
const emit=defineEmits<{select:[node:GraphNode]}>()
const container=ref<HTMLDivElement|null>(null)
const disabled=ref<EntityType[]>([])
let cy:cytoscape.Core|undefined
let observer:ResizeObserver|undefined
const keptPositions=new Map<string,cytoscape.Position>()
let lastLayoutKey:string|undefined
let layoutVariant=0
const allRelationLabels=ref(false)
const types=computed(()=>[...new Set(props.graph.nodes.map(n=>n.type))])
function applyVisibility(){
  if(!cy)return
  cy.nodes().forEach(n=>{n.toggleClass('type-hidden',disabled.value.includes(n.data('type')));n.toggleClass('picked',n.id()===props.selectedId)})
  cy.edges().forEach(e=>{e.toggleClass('type-hidden',e.source().hasClass('type-hidden')||e.target().hasClass('type-hidden'))})
  if(props.stableKnowledge){
    cy.edges().removeClass('b-relation-active b-all-labels')
    if(allRelationLabels.value)cy.edges().addClass('b-all-labels')
    else{
      const picked=cy.getElementById(props.selectedId)
      if(picked.length&&picked.data('type')!=='Paper')picked.connectedEdges().addClass('b-relation-active')
    }
  }
  cy.elements().removeClass('focused muted')
  const selected = cy.getElementById(props.selectedId)
  if((!props.overview&&!props.rootId)||!selected.length||!selected.visible()||props.selectedId===props.rootId)return
  const visible = cy.elements(':visible')
  const root = props.rootId?cy.getElementById(props.rootId):null
  const route = root?.length&&root.visible()
    ? visible.aStar({root,goal:selected,directed:false}).path
    : null
  const focus = route?.length?route:selected.closedNeighborhood()
  visible.difference(focus).addClass('muted')
  focus.addClass('focused')
}
function renderGraph(reset=false){
  if(!container.value)return
  if(!cy){
    cy=cytoscape({container:container.value,minZoom:props.stableKnowledge||props.overview||props.rootId ? 0.05 : 0.25,maxZoom:2.6,wheelSensitivity:.18,
      style:[
        {selector:'node',style:{width:26,height:26,'background-color':'data(color)',label:'data(shortLabel)',
          'font-size':11,'font-family':'Microsoft YaHei, sans-serif','text-valign':'bottom','text-margin-y':9,
          color:'#536a75','text-background-color':'#fbfdfe','text-background-opacity':.85,'text-background-padding':'3px',
          'border-width':2,'border-color':'#ffffff'}},
        {selector:'node[type="Paper"]',style:{width:21,height:21,shape:'ellipse'}},
        {selector:'node[type="Method"]',style:{shape:'round-rectangle',width:38,height:29}},
        {selector:'node[type="Dataset"]',style:{shape:'round-rectangle',width:35,height:27}},
        {selector:'node[type="ResearchDirection"]',style:{shape:'hexagon',width:38,height:34}},
        {selector:'edge',style:{width:1.6,'line-color':'#9ebcc5','target-arrow-color':'#7c9faa','target-arrow-shape':'triangle','arrow-scale':.8,'curve-style':'bezier',opacity:1,label:props.rootId?'':'data(relationLabel)','font-size':10,'text-background-color':'#fbfdfe','text-background-opacity':1,'text-background-padding':'3px',color:'#5d7883'}},
        {selector:'node.picked',style:{width:36,height:36,'border-width':5,'border-color':'#bce6de','z-index':10}},
        {selector:'node[isNew = 1]',style:{'border-style':'dashed','border-width':3,'border-color':'#8056ae'}},
        {selector:'node[hop = 0]',style:{width:40,height:40,'border-width':4,'border-color':'#236e61'}},
        {selector:'edge[isNew = 1]',style:{'line-style':'dashed','line-color':'#8056ae','target-arrow-color':'#8056ae'}},
        {selector:'node:active',style:{'overlay-opacity':0}},
        {selector:'.type-hidden',style:{display:'none'}},
        ...(props.overview?[
          {selector:'node[type="Paper"]',style:{width:11,height:11,label:''}},
          {selector:'node[type="Paper"].picked',style:{width:19,height:19,label:'data(shortLabel)'}},
          {selector:'edge',style:{width:1,'curve-style':'straight' as const,'target-arrow-shape':'none' as const,opacity:.27,label:''}},
        ]:[]),
        {selector:'edge.focused',style:{opacity:1,width:2.5,label:props.rootId?'data(relationLabel)':''}},
        {selector:'.muted',style:{opacity:.19}},
        ...(props.stableKnowledge?[
          {selector:'node',style:{width:34,height:34,'text-wrap':'wrap' as const,'text-max-width':'120px','font-size':16,'font-weight':500,'text-margin-y':9}},
          {selector:'node[type="Paper"]',style:{width:32,height:32}},
          {selector:'node[type="Method"], node[type="Dataset"]',style:{width:43,height:34}},
          {selector:'node[type="ResearchDirection"]',style:{width:44,height:40}},
          {selector:'node.picked',style:{width:42,height:42,'border-width':4}},
          {selector:'edge',style:{label:'',width:1.3,'arrow-scale':.7,'text-rotation':'autorotate' as const}},
          {selector:'edge.b-relation-active, edge.b-hovered, edge.b-all-labels',style:{label:'data(relationLabel)','z-index':8,'text-background-opacity':1}},
        ]:[]),
      ]})
    cy.on('tap','node',event=>{const node=props.graph.nodes.find(n=>n.id===event.target.id());if(node)emit('select',node)})
    if(props.stableKnowledge){
      cy.on('mouseover','edge',event=>event.target.addClass('b-hovered'))
      cy.on('mouseout','edge',event=>event.target.removeClass('b-hovered'))
    }
    observer=new ResizeObserver(()=>{cy?.resize();if(!props.stableKnowledge)cy?.fit(cy.elements(':visible'),38)});observer.observe(container.value)
  }
  const positions=new Map<string,cytoscape.Position>();cy.nodes().forEach(n=>{positions.set(n.id(),n.position())})
  let firstKnowledgeLayout=false
  if(props.stableKnowledge){
    const changed=lastLayoutKey!==props.layoutKey
    if(changed)layoutVariant=0
    else if(reset)layoutVariant++
    if(changed||reset)keptPositions.clear()
    else positions.forEach((p,id)=>keptPositions.set(id,p))
    firstKnowledgeLayout=!keptPositions.size
    lastLayoutKey=props.layoutKey
    const planned=knowledgePositions(props.graph.nodes,keptPositions,layoutVariant)
    positions.clear();planned.forEach((p,id)=>{positions.set(id,p);keptPositions.set(id,p)})
  }
  cy.batch(()=>{
    cy!.elements().remove()
    cy!.add([
      ...props.graph.nodes.map(n=>({group:'nodes' as const,data:{...n,isNew:Number(!!n.isNew),color:TYPE_COLORS[n.type],shortLabel:props.stableKnowledge?(n.label.length>30?n.label.slice(0,29)+'…':n.label):(n.label.length>14?n.label.slice(0,13)+'…':n.label)},position:positions.get(n.id)})),
      ...props.graph.edges.map(e=>({group:'edges' as const,data:{...e,isNew:Number(!!e.isNew),relationLabel:RELATION_NAMES[e.kind??e.type]??e.type}})),
    ])
  })
  applyVisibility()
  if(props.stableKnowledge){
    // Positions were explicitly planned; normal edits preserve zoom and pan.
  }else if(props.rootId){
    cy.layout({name:'concentric',animate:false,minNodeSpacing:38,padding:42,
      concentric:node=>2-(node.data('hop')??1),levelWidth:()=>1}).run()
  }else{
    cy.layout({name:'cose',animate:false,randomize:true,nodeRepulsion:()=>9500,idealEdgeLength:()=>85,
      nodeOverlap:25,componentSpacing:85,numIter:props.overview?180:400,padding:45}).run()
  }
  cy.resize()
  if(!props.stableKnowledge)cy.fit(cy.elements(':visible'),38)
  else if(firstKnowledgeLayout||reset){
    cy.fit(cy.elements(':visible'),24)
    // Do not shrink every label to fit a large graph. The explicit fit button
    // remains the full-graph overview; initial/reset views prioritize reading.
    if(cy.zoom()<.72){
      cy.zoom(.72)
      const paper=cy.nodes('[type="Paper"]:visible')
      if(paper.length)cy.center(paper)
    }
  }
}
function toggleType(type:EntityType){disabled.value=disabled.value.includes(type)?disabled.value.filter(t=>t!==type):[...disabled.value,type];applyVisibility()}
function zoom(factor:number){if(cy)cy.zoom({level:cy.zoom()*factor,renderedPosition:{x:cy.width()/2,y:cy.height()/2}})}
function fit(){cy?.fit(cy.elements(':visible'),38)}
watch(()=>props.graph,()=>nextTick(renderGraph))
watch(()=>props.selectedId,applyVisibility)
watch(allRelationLabels,applyVisibility)
onMounted(renderGraph)
onBeforeUnmount(()=>{observer?.disconnect();cy?.destroy()})
</script>
<template>
  <div class="graph-stage" :class="{'overview-stage':overview,'knowledge-stage':stableKnowledge}">
    <div ref="container" class="cy-canvas" role="img" :aria-label="`关联图谱：${graph.nodes.length}个节点，${graph.edges.length}条关系`"></div>
    <div class="graph-controls">
      <button class="icon-button" aria-label="放大图谱" @click="zoom(1.2)"><AppIcon name="zoomIn"/></button>
      <button class="icon-button" aria-label="缩小图谱" @click="zoom(.8)"><AppIcon name="zoomOut"/></button>
      <button class="icon-button" aria-label="适应画布" @click="fit"><AppIcon name="fit"/></button>
      <button class="icon-button" aria-label="重新布局" @click="renderGraph(true)"><AppIcon name="refresh"/></button>
    </div>
    <label v-if="stableKnowledge" class="relation-label-toggle"><input v-model="allRelationLabels" type="checkbox"/>显示全部关系文字</label>
    <div class="graph-legend" aria-label="节点类型筛选">
      <button v-for="type in types" :key="type" :class="{disabled:disabled.includes(type)}" :aria-pressed="!disabled.includes(type)" @click="toggleType(type)">
        <i :style="{background:TYPE_COLORS[type]}"></i>{{TYPE_LABELS[type]}}
      </button>
    </div>
  </div>
  <details class="graph-accessible">
    <summary>查看节点列表（可键盘操作）</summary>
    <div><button v-for="node in graph.nodes.filter(item=>!disabled.includes(item.type))" :key="node.id" class="text-button" @click="emit('select',node)">{{TYPE_LABELS[node.type]}} · {{node.label}}</button></div>
  </details>
</template>
<style scoped>
.relation-label-toggle{position:absolute;bottom:8px;left:14px;display:flex;align-items:center;gap:6px;font-size:13px;color:#536a75}.knowledge-stage .cy-canvas{bottom:110px}.knowledge-stage .graph-legend{bottom:38px}
.overview-stage{min-height:560px;background-color:#f2f8f9}
@media(max-width:700px){.overview-stage{min-height:420px}}
</style>
