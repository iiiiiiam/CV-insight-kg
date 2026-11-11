<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {graphResearch} from '../services/graph.ts'
import {EMPTY_FILTERS,TYPE_LABELS} from '../types.ts'
import type {GraphData,GraphNode} from '../types.ts'
import GraphPanel from './GraphPanel.vue'

const props = defineProps<{seed:string; batch:string}>()
const emit = defineEmits<{select:[id:string]}>()
const rootId = ref(props.seed)
const selectedId = ref(props.seed)
const hops = ref(1)
const loadedHops = ref(1)
const retry = ref(0)
const loading = ref(true)
const error = ref('')
const graph = ref<GraphData|null>(null)
const counts = ref({nodes:0,edges:0,visibleNodes:0,visibleEdges:0,limited:false})
const selected = computed(()=>graph.value?.nodes.find(node=>node.id===selectedId.value))

interface ExpansionParams {seed:string;batch_id:string;hops:number;limit:number}
interface Expansion extends GraphData {
  addedNodes:string[]
  addedEdges:string[]
  baselineTruncated:boolean
}
interface ExpansionModule {
  loadExpansion:(load:(params:ExpansionParams)=>Promise<GraphData>,params:ExpansionParams)=>Promise<Expansion>
  selectVisible:(data:Expansion,seed:string)=>Pick<GraphData,'nodes'|'edges'> & {limited:boolean}
}
watch([()=>props.seed,()=>props.batch],([seed])=>{
  graph.value = null
  rootId.value = seed
  selectedId.value = seed
  hops.value = 1
  retry.value++
})
watch([rootId,()=>props.batch,hops,retry],async ([seed,batch,depth],_,onCleanup)=>{
  const controller = new AbortController()
  onCleanup(()=>controller.abort())
  error.value = ''
  loading.value = true
  try{
    const componentUrl = '/api/components/c-graph-view.js'
    const {loadExpansion,selectVisible} = await import(/* @vite-ignore */ componentUrl) as ExpansionModule
    if(controller.signal.aborted)return
    const signal = AbortSignal.any([controller.signal,AbortSignal.timeout(45000)])
    const expanded = await loadExpansion(params=>graphResearch.getGraph(params.seed,params.hops,
      {...EMPTY_FILTERS,batch_id:params.batch_id},signal,params.limit),
    {seed,batch_id:batch,hops:depth,limit:60})
    if(controller.signal.aborted)return
    const visible = selectVisible(expanded,seed)
    counts.value = {
      nodes:expanded.addedNodes.length,edges:expanded.addedEdges.length,
      visibleNodes:visible.nodes.filter(node=>node.isNew).length,
      visibleEdges:visible.edges.filter(edge=>edge.isNew).length,limited:visible.limited,
    }
    graph.value = {...expanded,nodes:visible.nodes,edges:visible.edges,
      truncated:expanded.truncated||expanded.baselineTruncated}
    loadedHops.value = depth
    if(!visible.nodes.some(node=>node.id===selectedId.value))selectedId.value = seed
  }catch(cause){
    if(!controller.signal.aborted)error.value = cause instanceof Error?cause.message:'无法读取关联图谱。'
  }finally{
    if(!controller.signal.aborted)loading.value = false
  }
},{immediate:true})

function selectNode(node:GraphNode){
  selectedId.value = node.id
}
function exploreSelected(){
  graph.value = null
  rootId.value = selectedId.value
  hops.value = 1
}
</script>

<template>
  <div class="cross-toolbar">
    <button v-for="depth in [1,2]" :key="depth" type="button" class="button"
      :class="hops===depth?'button-primary':'button-secondary'"
      :aria-pressed="hops===depth" @click="hops=depth">{{depth}} 跳</button>
    <span v-if="loading" role="status">正在加载 {{hops}} 跳…</span>
  </div>
  <p v-if="error" class="inline-error" role="alert">{{error}}
    <button type="button" class="text-button" @click="retry++">重试</button>
  </p>
  <template v-if="graph">
    <p class="small-note">
      已加载 {{loadedHops}} 跳 · {{graph.nodes.length}} 节点 / {{graph.edges.length}} 关系
      <span v-if="graph.truncated"> · C 路径已截断</span>
      <span v-if="counts.limited"> · 画布仅展示前 60 个节点</span>
    </p>
    <p v-if="loadedHops===2" class="small-note">
      <template v-if="counts.nodes||counts.edges">紫色虚线为两跳新增。返回 {{counts.nodes}} 个新节点、{{counts.edges}} 条新关系，
        画布收录 {{counts.visibleNodes}} 个新节点、{{counts.visibleEdges}} 条新关系（应用类型筛选前）。</template>
      <template v-else>{{graph.truncated?'当前截断范围内未发现新增关联。':'未发现新的两跳关联。'}}</template>
    </p>
    <GraphPanel :graph="graph" :root-id="rootId" :selected-id="selectedId" @select="selectNode"/>
    <div v-if="selected" class="cross-toolbar selection">
      <span>{{selected.id===rootId?'当前起点':'已选节点'}} · {{TYPE_LABELS[selected.type]}} · <strong>{{selected.label}}</strong></span>
      <button type="button" class="text-button" @click="emit('select',selected.id)">查看详情与证据</button>
      <button v-if="selected.id!==rootId" type="button" class="text-button" @click="exploreSelected">从此节点重新展开</button>
    </div>
  </template>
</template>
<style scoped>
.cross-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0;font-size:13px}
.selection{padding:10px 12px;background:#eef7f4;border-radius:7px;overflow-wrap:anywhere}
</style>
