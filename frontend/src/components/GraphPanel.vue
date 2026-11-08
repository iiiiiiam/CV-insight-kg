<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import cytoscape from 'cytoscape'
import type {GraphData,GraphNode,EntityType} from '../types.ts'
import {TYPE_COLORS,TYPE_LABELS} from '../types.ts'
import AppIcon from './AppIcon.vue'

const props=defineProps<{graph:GraphData;selectedId:string}>()
const emit=defineEmits<{select:[node:GraphNode]}>()
const container=ref<HTMLDivElement|null>(null)
const disabled=ref<EntityType[]>([])
let cy:cytoscape.Core|undefined
let observer:ResizeObserver|undefined
const types=computed(()=>[...new Set(props.graph.nodes.map(n=>n.type))])
function applyVisibility(){
  if(!cy)return
  cy.nodes().forEach(n=>{n.toggleClass('type-hidden',disabled.value.includes(n.data('type')));n.toggleClass('picked',n.id()===props.selectedId)})
  cy.edges().forEach(e=>{e.toggleClass('type-hidden',e.source().hasClass('type-hidden')||e.target().hasClass('type-hidden'))})
}
function renderGraph(){
  if(!container.value)return
  if(!cy){
    cy=cytoscape({container:container.value,minZoom:.25,maxZoom:2.6,wheelSensitivity:.18,
      style:[
        {selector:'node',style:{width:26,height:26,'background-color':'data(color)',label:'data(shortLabel)',
          'font-size':11,'font-family':'Microsoft YaHei, sans-serif','text-valign':'bottom','text-margin-y':9,
          color:'#536a75','text-background-color':'#fbfdfe','text-background-opacity':.85,'text-background-padding':'3px',
          'border-width':2,'border-color':'#ffffff'}},
        {selector:'node[type="Paper"]',style:{width:21,height:21,shape:'ellipse'}},
        {selector:'node[type="Method"]',style:{shape:'round-rectangle',width:38,height:29}},
        {selector:'node[type="Dataset"]',style:{shape:'round-rectangle',width:35,height:27}},
        {selector:'edge',style:{width:1.6,'line-color':'#9ebcc5','target-arrow-color':'#7c9faa','target-arrow-shape':'triangle','arrow-scale':.8,'curve-style':'bezier',opacity:1,label:'data(type)','font-size':10,'text-background-color':'#fbfdfe','text-background-opacity':1,'text-background-padding':'3px',color:'#5d7883'}},
        {selector:'node.picked',style:{width:36,height:36,'border-width':5,'border-color':'#bce6de','z-index':10}},
        {selector:'node:active',style:{'overlay-opacity':0}},
        {selector:'.type-hidden',style:{display:'none'}},
      ]})
    cy.on('tap','node',event=>{const node=props.graph.nodes.find(n=>n.id===event.target.id());if(node)emit('select',node)})
    observer=new ResizeObserver(()=>{cy?.resize();cy?.fit(cy.elements(':visible'),38)});observer.observe(container.value)
  }
  const positions=new Map<string,cytoscape.Position>();cy.nodes().forEach(n=>{positions.set(n.id(),n.position())})
  cy.batch(()=>{
    cy!.elements().remove()
    cy!.add([
      ...props.graph.nodes.map(n=>({group:'nodes' as const,data:{...n,color:TYPE_COLORS[n.type],shortLabel:n.label.length>14?n.label.slice(0,13)+'…':n.label},position:positions.get(n.id)})),
      ...props.graph.edges.map(e=>({group:'edges' as const,data:e})),
    ])
  })
  applyVisibility()
  cy.layout({name:'cose',animate:false,randomize:true,nodeRepulsion:()=>9500,idealEdgeLength:()=>85,
    nodeOverlap:25,componentSpacing:85,numIter:400,padding:45}).run()
  cy.resize();cy.fit(cy.elements(':visible'),38)
}
function toggleType(type:EntityType){disabled.value=disabled.value.includes(type)?disabled.value.filter(t=>t!==type):[...disabled.value,type];applyVisibility()}
function zoom(factor:number){if(cy)cy.zoom({level:cy.zoom()*factor,renderedPosition:{x:cy.width()/2,y:cy.height()/2}})}
function fit(){cy?.fit(cy.elements(':visible'),38)}
watch(()=>props.graph,()=>nextTick(renderGraph))
watch(()=>props.selectedId,applyVisibility)
onMounted(renderGraph)
onBeforeUnmount(()=>{observer?.disconnect();cy?.destroy()})
</script>
<template>
  <div class="graph-stage">
    <div ref="container" class="cy-canvas" role="img" :aria-label="`关联图谱：${graph.nodes.length}个节点，${graph.edges.length}条关系`"></div>
    <div class="graph-controls">
      <button class="icon-button" aria-label="放大图谱" @click="zoom(1.2)"><AppIcon name="zoomIn"/></button>
      <button class="icon-button" aria-label="缩小图谱" @click="zoom(.8)"><AppIcon name="zoomOut"/></button>
      <button class="icon-button" aria-label="适应画布" @click="fit"><AppIcon name="fit"/></button>
      <button class="icon-button" aria-label="重新布局" @click="renderGraph"><AppIcon name="refresh"/></button>
    </div>
    <div class="graph-legend" aria-label="节点类型筛选">
      <button v-for="type in types" :key="type" :class="{disabled:disabled.includes(type)}" :aria-pressed="!disabled.includes(type)" @click="toggleType(type)">
        <i :style="{background:TYPE_COLORS[type]}"></i>{{TYPE_LABELS[type]}}
      </button>
    </div>
  </div>
  <details class="graph-accessible">
    <summary>查看节点列表（可键盘操作）</summary>
    <div><button v-for="node in graph.nodes" :key="node.id" class="text-button" @click="emit('select',node)">{{TYPE_LABELS[node.type]}} · {{node.label}}</button></div>
  </details>
</template>
