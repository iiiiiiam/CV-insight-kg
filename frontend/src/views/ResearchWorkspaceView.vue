<script setup lang="ts">
import {computed,nextTick,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import CrossPaperGraph from '../components/CrossPaperGraph.vue'
import DetailDrawer from '../components/DetailDrawer.vue'
import GraphPanel from '../components/GraphPanel.vue'
import MultiValueFilter from '../components/MultiValueFilter.vue'
import StatePanel from '../components/StatePanel.vue'
import {getGraphOverview,graphResearch,searchGraphEntities} from '../services/graph.ts'
import {knowledgePaperIdFromGraphId,researchResultQuery} from '../services/research-navigation.ts'
import {EMPTY_FILTERS,TYPE_LABELS} from '../types.ts'
import type {Filters,GraphNode,GraphOverview,MultiFilterValue,PaperSort} from '../types.ts'

const route = useRoute()
const router = useRouter()
const tabs = [
  {id:'papers',label:'论文'},
  {id:'entities',label:'作者与其他实体'},
  {id:'overview',label:'跨论文图谱总览'},
] as const
const relationFields = [
  {key:'author',label:'作者',kind:'Author'},
  {key:'institution',label:'机构',kind:'Institution'},
  {key:'topic',label:'主题',kind:'Topic'},
  {key:'method',label:'方法',kind:'Method'},
  {key:'task',label:'任务',kind:'Task'},
  {key:'dataset',label:'数据集',kind:'Dataset'},
  {key:'venue',label:'会议 / 期刊',kind:'Venue'},
] as const
const param = (key:string) => typeof route.query[key]==='string' ? route.query[key] : ''
const params = (key:string) => {
  const value=route.query[key]
  return (Array.isArray(value)?value:[value]).filter((item):item is string=>typeof item==='string'&&!!item)
}
const tab = computed(()=>tabs.find(item=>item.id===param('tab'))?.id??'papers')
const page = computed(()=>Math.max(1,Math.min(100000,parseInt(param('page'),10)||1)))
const pageSize = computed(()=>[20,50,100].includes(Number(param('page_size')))?Number(param('page_size')):20)
const requestedBatch = computed(()=>param('batch_id'))
const batch = ref('')
const filters = ref<Filters>({...EMPTY_FILTERS})
const kind = ref('author')
const entityQuery = ref('')
const rows = ref<Array<GraphNode & {note?:string;authors?:string[];venue?:string|null;citation_count?:number|null}>>([])
const total = ref(0)
const overview = ref<GraphOverview|null>(null)
const loading = ref(true)
const error = ref('')
const resultQuery = computed(()=>researchResultQuery(route.query))
const resultKey = computed(()=>JSON.stringify(resultQuery.value))
const selection = computed(()=>{
  const id = param('seed')
  if(!id)return null
  const node = (overview.value?.nodes??rows.value).find(item=>item.id===id)
  return {id,label:param('seed_label')||node?.label||id}
})
const drawer = computed(()=>!loading.value&&batch.value?param('detail')||null:null)
const graphSection = ref<HTMLElement|null>(null)
const resultSection = ref<HTMLElement|null>(null)
const refreshKey = ref(0)
const pageCount = computed(()=>Math.max(1,Math.ceil(total.value/pageSize.value)))

function values(value:MultiFilterValue|undefined){return Array.isArray(value)?value:(value?[value]:[])}
function setValues(key:keyof Filters,value:string[]){filters.value[key]=value as never}

function readFilters():Filters {
  const selectedSort=param('sort')
  const result:Filters = {...EMPTY_FILTERS,q:param('q'),year:param('year'),author_id:param('author_id'),
    sort:(['year_desc','year_asc','title'].includes(selectedSort)?selectedSort:'year_desc') as PaperSort}
  for(const {key} of relationFields){
    const selected=params(key)
    result[key] = selected.length>1?selected:(selected[0]??'')
  }
  return result
}

function setTab(value:typeof tabs[number]['id']){
  if(value===tab.value)return
  void router.push({path:'/research/papers',query:{tab:value,batch_id:batch.value||undefined}})
}
function search(){
  const query:Record<string,string|string[]> = {tab:tab.value,page_size:String(pageSize.value)}
  if(batch.value)query.batch_id = batch.value
  if(tab.value==='entities'){
    query.kind = kind.value
    if(entityQuery.value.trim())query.q = entityQuery.value.trim()
  }else{
    for(const [key,value] of Object.entries(filters.value)){
      if(key==='batch_id')continue
      const selected=Array.isArray(value)?value.map(item=>item.trim()).filter(Boolean):value?.trim()
      if(Array.isArray(selected)?selected.length:!!selected)query[key] = selected
    }
  }
  void router.replace({path:'/research/papers',query})
}
function reset(){
  filters.value = {...EMPTY_FILTERS}
  entityQuery.value = ''
  search()
}
function goToPage(value:number){
  void router.replace({query:{...resultQuery.value,page:String(value),batch_id:batch.value}})
}
function changePageSize(event:Event){
  void router.replace({query:{...resultQuery.value,page:undefined,page_size:(event.target as HTMLSelectElement).value,batch_id:batch.value}})
}
function relatedPapers(node:GraphNode){
  const field = node.type==='Author'?'author_id':relationFields.find(item=>item.kind===node.type)?.key
  if(field)void router.push({path:'/research/papers',query:{tab:'papers',batch_id:batch.value,[field]:node.id}})
}
function openPaper(id:string){
  const paperId=knowledgePaperIdFromGraphId(id)
  if(!paperId){
    void router.push({path:'/research/papers/'+encodeURIComponent(id),query:{...resultQuery.value,source:'c',batch_id:batch.value,return_to:route.fullPath}})
    return
  }
  void router.push({path:'/research/knowledge',query:{paper_id:paperId,from:'research',batch_id:batch.value,return_to:route.fullPath}})
}
function showDetail(id:string,type?:string){
  if(type==='Paper'){openPaper(id);return}
  const location = {query:{...route.query,detail:id}}
  if(drawer.value)void router.replace(location)
  else void router.push(location)
}
async function showGraph(id:string,label?:string){
  const query = {...resultQuery.value,seed:id,seed_label:label}
  if(drawer.value||selection.value)await router.replace({query})
  else await router.push({query})
  await nextTick()
  graphSection.value?.scrollIntoView({block:'nearest'})
}
function closeDetail(){
  const location = {query:{...route.query,detail:undefined}}
  if(router.options.history.state.back===router.resolve(location).fullPath)router.back()
  else void router.replace(location)
}
async function backToResults(){
  const location = {query:resultQuery.value}
  const back = router.options.history.state.back
  const previous = typeof back==='string'?router.resolve(back):null
  if(previous?.path===route.path&&!previous.query.seed&&!previous.query.detail
    &&JSON.stringify(researchResultQuery(previous.query))===resultKey.value)router.back()
  else {
    await router.replace(location)
    resultSection.value?.scrollIntoView({block:'start'})
  }
}
function latest(){
  batch.value = ''
  const query = {...resultQuery.value,batch_id:undefined}
  if(requestedBatch.value)void router.replace({query})
  else {
    void router.replace({query})
    refreshKey.value++
  }
}

watch([resultKey,refreshKey],async (_, __, onCleanup)=>{
  const controller = new AbortController()
  onCleanup(()=>controller.abort())
  const signal = AbortSignal.any([controller.signal,AbortSignal.timeout(45000)])
  const targetBatch = requestedBatch.value||batch.value
  loading.value = true
  error.value = ''
  rows.value = []
  overview.value = null
  filters.value = tab.value==='papers'?readFilters():{...EMPTY_FILTERS}
  entityQuery.value = tab.value==='entities'?param('q'):''
  kind.value = param('kind')||'author'
  try {
    if(tab.value==='overview'){
      const result = await getGraphOverview(targetBatch,signal)
      if(controller.signal.aborted)return
      overview.value = result
      batch.value = result.batch_id
    }else if(tab.value==='entities'){
      const result = await searchGraphEntities(entityQuery.value,kind.value,targetBatch,signal,page.value,pageSize.value)
      if(controller.signal.aborted)return
      if(typeof result.total!=='number')throw new Error('请重启 C 服务以启用实体分页。')
      rows.value = result.items
      total.value = result.total
      batch.value = result.batch_id
    }else{
      const result = await graphResearch.getPapers({...filters.value,batch_id:targetBatch},signal,page.value,pageSize.value)
      if(controller.signal.aborted)return
      rows.value = result.items.map(paper=>({
        id:paper.id,label:paper.title,type:'Paper',note:paper.year?String(paper.year):undefined,
        authors:paper.authors,venue:paper.venue,citation_count:paper.citation_count,
      }))
      total.value = result.total
      batch.value = result.batch_id
    }
  }catch(cause){
    if(!controller.signal.aborted)error.value = cause instanceof Error?cause.message:'读取失败，请重试。'
  }finally{
    if(!controller.signal.aborted)loading.value = false
  }
},{immediate:true})
</script>

<template>
  <section class="standard-page workspace">
    <header class="page-heading">
      <div><div class="eyebrow">文献调研</div><h1>公共知识检索</h1>
        <p>从论文、作者和其他实体进入同一批次的跨论文图谱。</p></div>
      <div class="actions"><RouterLink class="text-button" to="/research/raw-papers">A 原始论文</RouterLink>
        <RouterLink v-if="batch&&!loading&&!error" class="text-button" :to="{path:'/research/trends',query:{batch_id:batch}}">查看本批次分析</RouterLink>
        <button class="button button-secondary" type="button" @click="latest">读取最新发布</button></div>
    </header>

    <nav class="workspace-tabs" aria-label="文献调研视图">
      <button v-for="item in tabs" :key="item.id" type="button" class="button"
        :class="tab===item.id?'button-primary':'button-secondary'" :aria-pressed="tab===item.id"
        @click="setTab(item.id)">{{item.label}}</button>
    </nav>

    <form v-if="tab!=='overview'" class="panel search-card" role="search" @submit.prevent="search">
      <div v-if="tab==='papers'" class="search-fields">
        <label>论文标题<input v-model="filters.q" type="search" class="form-input" maxlength="200" placeholder="输入标题关键词"/></label>
        <label>年份<input v-model="filters.year" type="text" inputmode="numeric" pattern="[0-9]{4}" class="form-input" placeholder="例如 2024"/></label>
        <label>排序<select v-model="filters.sort" class="form-input"><option value="year_desc">年份从新到旧</option><option value="year_asc">年份从旧到新</option><option value="title">标题 A–Z</option></select></label>
      </div>
      <details v-if="tab==='papers'" :open="relationFields.some(({key})=>values(filters[key]).length>0)||!!filters.author_id">
        <summary>按关联实体筛选</summary>
        <p class="small-note">支持规范名称、已发布别名或稳定 ID；若名称存在歧义，请先在“作者与其他实体”中核对 ID。</p>
        <div class="search-fields">
          <MultiValueFilter v-for="field in relationFields" :key="field.key" :label="field.label"
            :model-value="values(filters[field.key])" placeholder="输入名称、别名或图谱 ID"
            @update:model-value="setValues(field.key,$event)"/>
        </div>
        <p v-if="filters.author_id" class="small-note">当前按作者 ID 筛选：{{filters.author_id}}
          <button type="button" class="text-button" @click="filters.author_id=''">移除作者限制</button>
        </p>
      </details>
      <div v-if="tab==='entities'" class="search-fields">
        <label>实体类型<select v-model="kind" class="form-input">
          <option v-for="item in relationFields" :key="item.kind" :value="item.kind.toLowerCase()">{{item.label}}</option>
        </select></label>
        <label>名称或完整图谱 ID<input v-model="entityQuery" type="search" class="form-input" maxlength="200"/></label>
      </div>
      <div class="actions"><button class="button button-primary">检索</button>
        <button type="button" class="button button-secondary" @click="reset">清空条件</button></div>
    </form>

    <StatePanel v-if="loading" kind="loading" title="正在读取已发布数据"/>
    <StatePanel v-else-if="error" kind="error" title="读取失败" :description="error" retry @retry="refreshKey++"/>
    <section v-else-if="overview" ref="resultSection" class="panel overview-card">
      <header>
        <h2>跨论文图谱总览</h2>
        <p>{{overview.paper_count}} 篇论文 · {{overview.hub_count}} 个共享实体 · {{overview.edges.length}} 条真实连接</p>
        <p class="small-note">小圆点代表论文，带名称的节点是至少关联两篇论文的共享实体。当前显示 {{overview.hub_count}} / {{overview.total_hubs}} 个共享实体，{{overview.linked_paper_count}} 篇论文有可见连线。点击任一节点可展开细看。</p>
      </header>
      <GraphPanel v-if="overview.nodes.length" :graph="overview" :selected-id="selection?.id??''" overview
        @select="node=>showGraph(node.id,node.label)"/>
      <StatePanel v-else kind="empty" title="当前批次没有可展示的论文"/>
    </section>
    <section v-else ref="resultSection" class="panel results-card">
      <header><div><h2>检索结果</h2><p>{{total}} {{tab==='papers'?'篇论文':'个实体'}} · 发布批次 {{batch}}</p></div>
        <label class="page-size">每页<select class="form-input" :value="pageSize" @change="changePageSize"><option :value="20">20</option><option :value="50">50</option><option :value="100">100</option></select>条</label></header>
      <StatePanel v-if="!rows.length" kind="empty" title="没有找到符合条件的结果"/>
      <article v-for="item in rows" :key="item.id" class="result-row">
        <div><small>{{TYPE_LABELS[item.type]}}{{item.note?' · '+item.note:''}}</small>
          <strong>{{item.label}}</strong>
          <p v-if="item.type==='Paper'" class="paper-summary">
            <span>会议：{{item.venue||'未知'}}</span><span>作者：{{item.authors?.length?item.authors.join('、'):'未知'}}</span>
            <span>引用数：{{item.citation_count??'未知'}}</span>
          </p>
          <small v-if="item.type!=='Paper'" class="entity-id">{{item.id}}</small></div>
        <div class="actions">
          <RouterLink v-if="item.type==='Author'" class="text-button"
            :to="{path:'/research/authors/'+encodeURIComponent(item.id),query:{...resultQuery,batch_id:batch}}">查看作者画像</RouterLink>
          <button type="button" class="text-button" @click="showDetail(item.id,item.type)">{{item.type==='Paper'?'知识与证据':'查看详情'}}</button>
          <button v-if="tab==='entities'" type="button" class="text-button" @click="relatedPapers(item)">关联论文</button>
          <button type="button" class="button button-secondary" @click="showGraph(item.id,item.label)">查看关联图谱</button>
        </div>
      </article>
      <footer v-if="pageCount>1" class="actions pagination">
        <button type="button" class="button button-secondary" :disabled="page<=1" @click="goToPage(page-1)">上一页</button>
        <span>第 {{page}} / {{pageCount}} 页</span>
        <button type="button" class="button button-secondary" :disabled="page>=pageCount" @click="goToPage(page+1)">下一页</button>
      </footer>
    </section>
    <section v-if="selection&&batch&&!loading&&!error" ref="graphSection" class="panel local-graph">
      <div class="graph-heading"><h2>关联图谱</h2>
        <button type="button" class="button button-secondary" @click="backToResults">{{tab==='overview'?'返回图谱总览':'返回检索结果'}}</button>
      </div>
      <p class="small-note">从「{{selection.label}}」打开，展示同一发布批次的关联。两跳可经共享实体发现其他论文。</p>
      <CrossPaperGraph :seed="selection.id" :batch="batch" @select="showDetail"/>
    </section>
    <DetailDrawer :id="drawer" source="c" :batch-id="batch" @close="closeDetail"
      @paper="id=>showDetail(id,'Paper')" @navigate="showDetail" @explore="showGraph"/>
  </section>
</template>

<style scoped>
.workspace{padding-bottom:28px}
.workspace-tabs,.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.workspace-tabs{margin:0 0 18px}
.search-card,.local-graph{padding:20px;margin:0 0 20px}
.local-graph{margin-top:20px}
.graph-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.search-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:12px 0}
.search-fields label{font-size:13px}
.search-fields .form-input{margin-top:5px}
.search-card details{margin:14px 0}
.search-card summary{cursor:pointer;font-size:13px}
.results-card header,.overview-card header{padding:18px 20px;border-bottom:1px solid #e6edef}.results-card header{display:flex;align-items:center;justify-content:space-between;gap:12px}
.results-card header p,.overview-card header p,.local-graph p{margin:7px 0;font-size:13px;line-height:1.7}
.result-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid #e6edef}
.result-row strong,.result-row small{display:block;overflow-wrap:anywhere}
.result-row strong{margin:5px 0;font-size:14px}
.paper-summary{display:flex;gap:6px 18px;flex-wrap:wrap;margin:5px 0;color:#587681;font-size:12px;line-height:1.6}.page-size{display:flex;align-items:center;gap:6px;font-size:12px;white-space:nowrap}.page-size .form-input{width:72px}
.entity-id{color:#648073}
.result-row .actions{flex-shrink:0}
.pagination{justify-content:center;padding:14px}
@media(max-width:860px){.result-row{align-items:flex-start;flex-direction:column}}
</style>
