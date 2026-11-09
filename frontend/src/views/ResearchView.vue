<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import type {CNode,Filters,GraphData,GraphNode,Paper} from '../types.ts'
import {TYPE_LABELS} from '../types.ts'
import {rawResearch} from '../services/research.ts'
import {graphResearch,searchGraphEntities} from '../services/graph.ts'
import AppIcon from '../components/AppIcon.vue'
import StatePanel from '../components/StatePanel.vue'
import GraphPanel from '../components/GraphPanel.vue'
import DetailDrawer from '../components/DetailDrawer.vue'

const route=useRoute(),router=useRouter()
const raw=computed(()=>route.path==='/research/raw-papers')
const papers=ref<Paper[]>([]),total=ref(0),loading=ref(true),error=ref(''),batch=ref(''),pinned=ref('')
const selectedId=ref(''),seed=ref(''),detailId=ref<string|null>(null),detailType=ref('Paper'),hops=ref(1)
const graph=ref<GraphData>({nodes:[],edges:[],truncated:false,batch_id:''}),graphLoading=ref(false),graphError=ref('')
const topics=ref<CNode[]>([]),methods=ref<CNode[]>([]),termsNotice=ref('')
const nodeQuery=ref(''),nodeKind=ref(''),nodeResults=ref<CNode[]>([]),nodeError=ref(''),nodeLoading=ref(false),nodeTruncated=ref(false)
const keyword=ref(String(route.query.q??''))
let generation=0,graphGeneration=0,nodeGeneration=0,controller:AbortController|undefined,graphController:AbortController|undefined,nodeController:AbortController|undefined
const filters=computed<Filters>(()=>({q:String(route.query.q??''),topic:String(route.query.topic??''),method:String(route.query.method??''),year:String(route.query.year??''),batch_id:String(route.query.batch_id??'')}))
const activeCount=computed(()=>Object.values(filters.value).filter(Boolean).length)
const selectedPaper=computed(()=>papers.value.find(p=>p.id===selectedId.value))
const paperCount=computed(()=>loading.value?'…':error.value?'—':total.value)
const entityTypeCount=computed(()=>loading.value||graphLoading.value?'…':error.value||graphError.value?'—':new Set(graph.value.nodes.map(n=>n.type)).size)
const relationTypeCount=computed(()=>loading.value||graphLoading.value?'…':error.value||graphError.value?'—':new Set(graph.value.edges.map(e=>e.type)).size)
const currentFilters=()=>({...filters.value,batch_id:raw.value?filters.value.batch_id:(filters.value.batch_id||pinned.value)})
function change(key:keyof Filters,value:string){const clean=value.trim();if(key==='batch_id')pinned.value='';const query={...route.query};if(clean)query[key]=clean;else delete query[key];void router.replace({path:route.path,query})}
function submitKeyword(){change('q',keyword.value)}
async function latest(){pinned.value='';await router.replace({path:route.path,query:{...route.query,batch_id:undefined}});await loadPapers()}
function reset(){pinned.value='';void router.replace({path:route.path,query:route.query.view?{view:route.query.view}:{}});if(!activeCount.value)void loadPapers()}
async function loadGraph(){
  const current=++graphGeneration;graphController?.abort();graphError.value=''
  if(!seed.value){graph.value={nodes:[],edges:[],truncated:false,batch_id:batch.value};graphLoading.value=false;return}
  graphController=new AbortController();graphLoading.value=true
  try{
    const gateway=raw.value?rawResearch:graphResearch
    const value=await gateway.getGraph(seed.value,raw.value?1:hops.value,currentFilters(),graphController.signal)
    if(current!==graphGeneration)return
    if(value.batch_id!==batch.value)throw new Error('图谱与列表批次不一致，请重新读取。')
    graph.value=value
  }catch(e){if(current===graphGeneration&&!(e instanceof DOMException&&e.name==='AbortError')){graphError.value=e instanceof Error?e.message:'图谱加载失败';graph.value={nodes:[],edges:[],truncated:false,batch_id:batch.value}}}
  finally{if(current===graphGeneration)graphLoading.value=false}
}
async function loadPapers(){
  const current=++generation;controller?.abort();graphController?.abort();graphGeneration++;nodeController?.abort();nodeGeneration++
  nodeResults.value=[];nodeLoading.value=false;nodeError.value='';controller=new AbortController();loading.value=true;error.value='';graphError.value='';detailId.value=null;topics.value=[];methods.value=[];termsNotice.value=''
  try{
    const value=await (raw.value?rawResearch:graphResearch).getPapers(currentFilters(),controller.signal)
    if(current!==generation)return
    papers.value=value.items;total.value=value.total;batch.value=value.batch_id
    if(!raw.value)pinned.value=value.batch_id
    if(!value.items.some(p=>p.id===selectedId.value))selectedId.value=value.items[0]?.id??''
    seed.value=!raw.value&&route.query.seed?String(route.query.seed):selectedId.value
    await loadGraph()
    if(!raw.value){
      try{
        const [t,m]=await Promise.all([searchGraphEntities('','topic',batch.value,controller.signal),searchGraphEntities('','method',batch.value,controller.signal)])
        if(current===generation){topics.value=t.items;methods.value=m.items;if(t.truncated||m.truncated)termsNotice.value='候选项超过100条，可输入精确名称或 ID。'}
      }catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))termsNotice.value='筛选候选项暂不可用，可手动输入精确名称或 ID。'}
    }
  }catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError')){error.value=e instanceof Error?e.message:'列表加载失败';papers.value=[];total.value=0;batch.value='';selectedId.value='';seed.value='';graphLoading.value=false;graph.value={nodes:[],edges:[],truncated:false,batch_id:''}}}
  finally{if(current===generation)loading.value=false}
}
async function pickPaper(id:string){selectedId.value=id;seed.value=id;await loadGraph()}
function openDetail(id:string,type='Paper'){detailType.value=type;detailId.value=id}
function pickNode(node:GraphNode){openDetail(node.id,node.type)}
async function explore(id:string){detailId.value=null;seed.value=id;await loadGraph()}
async function searchNodes(){
  const current=++nodeGeneration;nodeController?.abort();nodeController=new AbortController();nodeLoading.value=true;nodeError.value='';nodeResults.value=[]
  try{const result=await searchGraphEntities(nodeQuery.value,nodeKind.value,batch.value,nodeController.signal);if(current===nodeGeneration){nodeResults.value=result.items;nodeTruncated.value=result.truncated}}
  catch(e){if(current===nodeGeneration&&!(e instanceof DOMException&&e.name==='AbortError'))nodeError.value=e instanceof Error?e.message:'节点检索失败'}
  finally{if(current===nodeGeneration)nodeLoading.value=false}
}
watch([filters,raw],(_v,old)=>{if(old&&old[1]!==raw.value){pinned.value='';batch.value='';selectedId.value='';hops.value=1}void loadPapers()},{immediate:true})
watch(()=>route.query.q,value=>{keyword.value=String(value??'')})
watch(hops,()=>void loadGraph())
onBeforeUnmount(()=>{generation++;graphGeneration++;nodeGeneration++;controller?.abort();graphController?.abort();nodeController?.abort()})
</script>
<template><section class="research-page">
  <div class="page-heading"><div><div class="eyebrow">RESEARCH EXPLORER</div><h1>{{raw?'A 原始论文':'公共知识图谱研究'}}</h1><p>{{raw?'原始元数据与导入批次，不代表公共知识结论。':'公共知识由 B 自动抽取并根据管理员反馈更新；C 展示已同步发布的有效公共知识快照。'}}</p></div><button class="button button-secondary" @click="loadPapers"><AppIcon name="refresh"/>刷新当前范围</button></div>
  <div class="source-tabs"><RouterLink to="/research/papers">公共知识图谱（C）</RouterLink><RouterLink to="/research/raw-papers">原始论文（A）</RouterLink><button v-if="!raw" class="text-button" @click="latest">读取当前 C 结果</button></div>
  <div class="mock-banner api-banner"><AppIcon name="info"/><span>{{raw?'当前仅展示 A 元数据及论文—会议关系。':'B 的当前公共知识、个人调整和反馈均可查看；管理员处理反馈后会请求同步到 C，失败时可在管理员同步页重试。'}}<RouterLink v-if="!raw" to="/research/knowledge">查看知识与证据</RouterLink></span></div>
  <div v-if="error&&!raw" class="research-unavailable" role="note"><p>当前未能读取 C 图谱查询结果，论文数量未知。请检查 C 服务（8002）、Neo4j、服务令牌和是否已有同步发布的有效知识快照。</p><RouterLink to="/research/knowledge" class="button button-secondary">查看 B 知识与证据</RouterLink><span>A 原始论文、B 当前知识和 C 图谱查询分别读取。</span></div>
  <div class="overview-strip"><div><span class="metric-value">{{paperCount}}</span><span class="metric-label">匹配论文</span></div><div><span class="metric-value">{{entityTypeCount}}</span><span class="metric-label">实体类型</span></div><div><span class="metric-value">{{relationTypeCount}}</span><span class="metric-label">关系类型</span></div><div class="overview-right">批次 / 范围：{{batch||'尚未读取'}}</div></div>
  <section class="filter-panel"><div class="filter-caption"><AppIcon name="search"/><strong>筛选研究范围</strong></div>
    <form class="keyword-field" role="search" @submit.prevent="submitKeyword"><label for="research-keyword">{{raw?'标题 / 摘要关键词':'论文标题关键词'}}</label><div class="keyword-search-controls"><input id="research-keyword" v-model="keyword" type="search" class="form-input" maxlength="200" placeholder="输入关键词后按 Enter 或点击检索"/><button class="button button-secondary">检索</button></div></form>
    <div class="filter-fields"><template v-if="!raw"><label>主题（精确名称或 ID）<input class="form-input" list="graph-topics" :value="filters.topic" @change="change('topic',($event.target as HTMLInputElement).value)"/><datalist id="graph-topics"><option v-for="item in topics" :key="item.id" :value="item.name"/></datalist></label><label>方法（精确名称或 ID）<input class="form-input" list="graph-methods" :value="filters.method" @change="change('method',($event.target as HTMLInputElement).value)"/><datalist id="graph-methods"><option v-for="item in methods" :key="item.id" :value="item.name"/></datalist></label></template><label>年份<input class="form-input" type="number" :min="raw?1980:1900" max="2100" :value="filters.year" @change="change('year',($event.target as HTMLInputElement).value)"/></label><label>{{raw?'A 导入批次 ID':'C 已发布批次 ID'}}<input class="form-input" :type="raw?'number':'text'" :value="filters.batch_id" :placeholder="raw?'全部导入批次':'留空时固定当前读取批次'" @change="change('batch_id',($event.target as HTMLInputElement).value)"/></label><button class="text-button" @click="reset">重置</button></div><p v-if="termsNotice" class="small-note">{{termsNotice}}</p>
  </section>
  <section v-if="!raw" class="panel node-search"><h2>节点检索与定位</h2><form @submit.prevent="searchNodes"><input v-model="nodeQuery" class="form-input" aria-label="节点名称或 ID" placeholder="节点名称或完整 ID"/><select v-model="nodeKind" class="form-input" aria-label="节点类型"><option value="">全部类型</option><option v-for="(label,key) in TYPE_LABELS" :key="key" :value="key.toLowerCase()">{{label}}</option></select><button class="button button-secondary" :disabled="!batch||loading||nodeLoading">{{nodeLoading?'正在检索':'检索节点'}}</button></form><p v-if="nodeError" class="inline-error">{{nodeError}}</p><div class="node-results"><button v-for="node in nodeResults" :key="node.id" class="text-button" @click="explore(node.id)">{{TYPE_LABELS[node.type]}} · {{node.name}}</button></div><p v-if="nodeTruncated" class="small-note">只显示前100项，请缩小关键词范围。</p></section>
  <div class="research-grid"><section class="panel papers-panel"><header class="panel-header"><div><h2>论文列表 <span>{{paperCount}}</span></h2><small>{{raw?'A 记录顺序':'年份降序；最多展示当前前100篇'}}</small></div></header><StatePanel v-if="loading" kind="loading" title="正在读取论文与图谱"/><StatePanel v-else-if="error" kind="error" title="论文数据尚不可用" :description="error" retry @retry="loadPapers"/><StatePanel v-else-if="!papers.length" kind="empty" title="没有符合条件的论文" description="当前批次没有匹配记录，可清除筛选条件。"/><div v-else class="paper-list"><article v-for="paper in papers" :key="paper.id" class="paper-row" :class="{selected:paper.id===selectedId}"><div class="paper-year">{{paper.year}}</div><div class="paper-main"><button class="paper-pick" :aria-pressed="paper.id===selectedId" @click="pickPaper(paper.id)"><span class="paper-title">{{paper.title}}</span><span class="paper-authors">{{paper.authors.length?paper.authors.join(' · '):'作者见同批图谱详情'}}</span></button><div class="paper-tags"><span>{{paper.source}}</span><small>{{paper.openalex_id.split('/').pop()||paper.id}}</small></div></div><button class="icon-button" :aria-label="`查看论文详情 ${paper.id}`" @click="openDetail(paper.id)"><AppIcon name="arrow"/></button></article></div><footer class="panel-footer">{{loading?'正在读取论文…':error?'读取失败，论文数量未知':`显示 ${papers.length} / ${total} 篇`}} · {{error?'尚未取得有效结果':batch}}</footer></section>
    <section class="panel graph-panel"><header class="panel-header"><div><h2>{{raw?'元数据关系图':'已发布知识图谱'}}</h2><small>{{raw?'A 论文—会议':'C 真实 Neo4j 查询；关系表示提及等已定义含义'}}</small></div><div class="hop-switch"><button :class="{active:hops===1}" @click="hops=1">1 跳</button><button :disabled="raw" :class="{active:hops===2}" @click="hops=2">2 跳</button></div></header><div v-if="selectedPaper" class="graph-focus">{{selectedPaper.title}}</div><StatePanel v-if="loading||graphLoading" kind="loading" title="正在展开关系"/><StatePanel v-else-if="error" kind="error" title="图谱暂不可用" description="论文数据尚未读取成功，无法确定同批图谱。"/><StatePanel v-else-if="graphError" kind="error" title="图谱读取失败" :description="graphError" retry @retry="loadGraph"/><StatePanel v-else-if="!graph.nodes.length" kind="empty" title="暂无图谱"/><GraphPanel v-else :graph="graph" :selected-id="seed" @select="pickNode"/><footer class="panel-footer" v-if="!loading&&!graphLoading&&!error&&!graphError">{{graph.nodes.length}} 节点 · {{graph.edges.length}} 关系 · {{graph.truncated?'已截断，请缩小范围':raw?'元数据关系':'最多100条路径；1—2跳'}} </footer></section></div>
  <DetailDrawer :id="detailId" :type="detailType" :source="raw?'a':'c'" :batch-id="raw?undefined:batch" @close="detailId=null" @paper="id=>openDetail(id)" @navigate="openDetail" @explore="explore"/>
</section></template>
<style scoped>.research-unavailable{padding:16px;border:1px solid #ead9b4;background:#fffbf2;border-radius:8px;margin-top:16px;font-size:12px;line-height:1.8}.research-unavailable .button{margin-top:10px}.research-unavailable>span{display:block;color:#7c8f98;margin-top:8px}.source-tabs{display:flex;align-items:center;gap:20px;margin:16px 0;font-size:13px}.source-tabs a{color:#568074}.source-tabs .router-link-active{font-weight:700;color:#147e6e}.keyword-search-controls{display:flex;align-items:center;gap:8px;max-width:720px}.keyword-search-controls .form-input{flex:1;max-width:none}.keyword-search-controls .button{flex:none;margin-top:6px}.node-search{padding:20px;margin:18px 0}.node-search h2{margin-bottom:14px}.node-search form{display:flex;gap:12px}.node-search input{flex:2}.node-search select{flex:1}.node-results{display:flex;gap:14px;flex-wrap:wrap;margin-top:14px}@media(max-width:700px){.keyword-search-controls{align-items:stretch;flex-direction:column}.keyword-search-controls .button{margin-top:0}.node-search form{flex-direction:column}.source-tabs{flex-wrap:wrap}.overview-strip{flex-wrap:wrap}}</style>
