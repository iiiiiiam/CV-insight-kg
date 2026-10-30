<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import type {Filters,GraphData,GraphNode,Paper} from '../types.ts'
import {research} from '../services/research.ts'
import AppIcon from '../components/AppIcon.vue'
import StatePanel from '../components/StatePanel.vue'
import GraphPanel from '../components/GraphPanel.vue'
import DetailDrawer from '../components/DetailDrawer.vue'

const route=useRoute(),router=useRouter()
const papers=ref<Paper[]>([]),total=ref(0),loading=ref(false),error=ref(''),batch=ref('')
const selectedId=ref(''),detailId=ref<string|null>(null),detailType=ref('Paper'),hops=ref(1)
const graph=ref<GraphData>({nodes:[],edges:[],truncated:false,batch_id:''}),graphLoading=ref(false),graphError=ref('')
let generation=0,graphGeneration=0,controller:AbortController|undefined,graphController:AbortController|undefined
const filters=computed<Filters>(()=>({q:String(route.query.q??''),topic:String(route.query.topic??''),method:String(route.query.method??''),year:String(route.query.year??''),batch_id:String(route.query.batch_id??'')}))
const supportsGraph=true
const entityTypes=computed(()=>new Set(graph.value.nodes.map(n=>n.type)).size)
const relationTypes=computed(()=>new Set(graph.value.edges.map(e=>e.type)).size)
const activeCount=computed(()=>Object.values(filters.value).filter(Boolean).length)
const selectedPaper=computed(()=>papers.value.find(p=>p.id===selectedId.value))
function change(key:keyof Filters,value:string){const query={...route.query};if(value)query[key]=value;else delete query[key];void router.replace({path:route.path,query})}
function reset(){void router.replace({path:route.path,query:route.query.view?{view:route.query.view}:{}})}
async function loadGraph(){
  const current=++graphGeneration;graphController?.abort();graphError.value=''
  if(!supportsGraph){graph.value={nodes:[],edges:[],truncated:false,batch_id:batch.value};graphLoading.value=false;return}
  if(!selectedId.value){graph.value={nodes:[],edges:[],truncated:false,batch_id:batch.value};graphLoading.value=false;return}
  const seed=selectedId.value;graphController=new AbortController();graphLoading.value=true
  try{
    const data=await research.getGraph(seed,hops.value,filters.value,graphController.signal)
    if(current!==graphGeneration)return
    if(data.batch_id!==batch.value)throw new Error('图谱与列表的数据批次不同，请刷新后重试。')
    graph.value=data
  }catch(e){if(current===graphGeneration&&!(e instanceof DOMException&&e.name==='AbortError')){graphError.value=e instanceof Error?e.message:'图谱加载失败';graph.value={nodes:[],edges:[],truncated:false,batch_id:batch.value}}}
  finally{if(current===graphGeneration)graphLoading.value=false}
}
async function loadPapers(){
  const current=++generation;controller?.abort();graphController?.abort();graphGeneration++;controller=new AbortController();loading.value=true;error.value='';graphError.value=''
  try{
    const data=await research.getPapers(filters.value,controller.signal)
    if(current!==generation)return
    papers.value=data.items;total.value=data.total;batch.value=data.batch_id
    if(!data.items.some(p=>p.id===selectedId.value))selectedId.value=data.items[0]?.id??''
    await loadGraph()
  }catch(e){
    if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError')){
      error.value=e instanceof Error?e.message:'列表加载失败';papers.value=[];total.value=0;selectedId.value='';graphLoading.value=false;graph.value={nodes:[],edges:[],truncated:false,batch_id:''}
    }
  }finally{if(current===generation)loading.value=false}
}
async function pickPaper(id:string){if(selectedId.value===id)return;selectedId.value=id;await loadGraph()}
function openPaper(id:string){detailType.value='Paper';detailId.value=id}
function pickNode(node:GraphNode){detailType.value=node.type;detailId.value=node.id}
watch(filters,()=>void loadPapers(),{immediate:true})
watch(hops,()=>void loadGraph())
onBeforeUnmount(()=>{controller?.abort();graphController?.abort()})
</script>
<template>
  <section class="research-page">
    <div class="page-heading"><div><div class="eyebrow">RESEARCH EXPLORER</div><h1>CV 研究工作台<span class="badge badge-outline">D 端原型</span></h1><p>检索真实论文，查看元数据、原始来源和会议关系。</p></div><button class="button button-secondary" @click="loadPapers"><AppIcon name="refresh"/>刷新视图</button></div>
    <div class="mock-banner api-banner"><AppIcon name="info"/><span>A 真实元数据已接入 · B 候选可在管理端只读查看 · C 正式图谱待接入，当前仅展示论文—会议关系。</span></div>
    <div class="overview-strip"><div><span class="metric-value">{{total.toString().padStart(2,'0')}}</span><span class="metric-label">匹配论文<small>当前筛选结果</small></span></div><i></i><div><span class="metric-value">{{entityTypes}}</span><span class="metric-label">实体类型<small>当前元数据图</small></span></div><i></i><div><span class="metric-value">{{relationTypes}}</span><span class="metric-label">关系类型<small>当前元数据图</small></span></div><div class="overview-right"><AppIcon name="layers" :size="16"/><span>范围 <strong>{{batch||'—'}}</strong></span></div></div>
    <section class="filter-panel" aria-label="论文筛选">
      <div class="filter-caption"><AppIcon name="search"/><strong>筛选研究范围</strong><small v-if="activeCount">{{activeCount}} 项条件</small></div>
      <label class="keyword-field">标题 / 摘要关键词<input type="search" class="form-input" :value="filters.q" maxlength="200" placeholder="输入关键词后按 Enter 或移出输入框" @change="change('q',($event.target as HTMLInputElement).value)"/></label>
      <div class="filter-fields">
        <label>研究主题<select disabled title="等待 B 审核与 C 正式查询"><option>待 B 审核 / C 接入</option></select></label>
        <label>研究方法<select disabled title="等待 B 审核与 C 正式查询"><option>待 B 审核 / C 接入</option></select></label>
        <label>发表年份<input class="form-input" type="number" min="1980" max="2100" :value="filters.year" placeholder="全部年份" @change="change('year',($event.target as HTMLInputElement).value)"/></label>
        <label>A 批次 ID<input class="form-input" type="number" min="1" :value="filters.batch_id" placeholder="全部批次" @change="change('batch_id',($event.target as HTMLInputElement).value)"/></label>
        <button class="text-button reset-button" :disabled="!activeCount" @click="reset"><AppIcon name="refresh" :size="14"/>重置条件</button>
      </div>
      <div v-if="filters.q" class="query-chip">关键词：{{filters.q}}<button class="icon-button" aria-label="清除关键词" @click="change('q','')"><AppIcon name="close" :size="13"/></button></div>
    </section>
    <div class="research-grid">
      <section class="panel papers-panel" aria-labelledby="papers-heading">
        <header class="panel-header"><div><h2 id="papers-heading">论文列表 <span>{{total}}</span></h2><small>选择论文，在右侧展开会议关系</small></div><span class="sort-label">A 接口顺序<AppIcon name="down" :size="13"/></span></header>
        <StatePanel v-if="loading" kind="loading" title="正在检索论文" description="正在同步筛选条件与图谱。"/>
        <StatePanel v-else-if="error" kind="error" title="论文加载失败" :description="error" retry @retry="loadPapers"/>
        <StatePanel v-else-if="!papers.length" kind="empty" title="没有符合条件的论文" description="试着清除关键词、年份或批次条件。"/>
        <div v-else class="paper-list">
          <article v-for="paper in papers" :key="paper.id" class="paper-row" :class="{selected:paper.id===selectedId}">
            <div class="paper-year">{{paper.year}}<span v-if="paper.id===selectedId" class="selected-mark"><AppIcon name="check" :size="12"/></span></div>
            <div class="paper-main"><button class="paper-pick" :aria-pressed="paper.id===selectedId" @click="pickPaper(paper.id)"><span class="paper-title">{{paper.title}}</span><span class="paper-authors">{{paper.authors.join(' · ')}}</span></button><div class="paper-tags"><span>{{paper.venue}}</span><span class="method-tag">{{paper.source}}</span><small>{{paper.openalex_id.split('/').pop()}}</small></div></div>
            <button class="icon-button paper-detail-button" :aria-label="`查看论文详情 ${paper.id}`" title="查看论文详情" @click="openPaper(paper.id)"><AppIcon name="arrow" :size="17"/></button>
          </article>
        </div>
        <footer class="panel-footer"><span>{{papers.length?`显示 ${papers.length} 条记录`:'暂无结果'}}</span><span>稳定ID · 来源可追溯</span></footer>
      </section>
      <section class="panel graph-panel" aria-labelledby="graph-heading">
        <header class="panel-header"><div><h2 id="graph-heading">元数据关系图 <span class="live-dot"></span></h2><small>A 元数据 · PUBLISHED_IN · C 正式图谱待接入</small></div><div class="hop-switch" aria-label="图谱跳数"><button class="active" aria-pressed="true">1 跳</button><button disabled title="等待 C 正式图谱接入">2 跳待接入</button></div></header>
        <div class="graph-focus" v-if="selectedPaper"><AppIcon name="book" :size="14"/><span>{{selectedPaper.title}}</span><button class="text-button" @click="openPaper(selectedPaper.id)">详情<AppIcon name="chevron" :size="12"/></button></div>
        <StatePanel v-if="loading||graphLoading" kind="loading" title="正在展开关系"/>
        <StatePanel v-else-if="graphError" kind="error" title="图谱加载失败" :description="graphError" retry @retry="loadGraph"/>
        <StatePanel v-else-if="!graph.nodes.length" kind="empty" title="暂无元数据关系" description="选择一篇论文查看 A 已提供的会议关系。"/>
        <GraphPanel v-else :graph="graph" :selected-id="selectedId" @select="pickNode"/>
        <footer class="panel-footer"><span>{{graph.nodes.length}} 节点 <b>·</b> {{graph.edges.length}} 关系</span><span>{{graph.truncated?'已达上限，请缩小范围':'拖动节点 · 滚轮缩放 · 点击查看详情'}}</span></footer>
      </section>
    </div>
    <div class="research-note"><AppIcon name="shield" :size="15"/><span>研究端匿名只读。管理员登录与受保护测试使用真实后台会话。</span><RouterLink to="/admin/access-check">验证权限<AppIcon name="arrow" :size="14"/></RouterLink></div>
    <DetailDrawer :id="detailId" :type="detailType" @close="detailId=null" @paper="openPaper"/>
  </section>
</template>
