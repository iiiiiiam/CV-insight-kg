<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import CrossPaperGraph from '../components/CrossPaperGraph.vue'
import DetailDrawer from '../components/DetailDrawer.vue'
import StatePanel from '../components/StatePanel.vue'
import {getAuthorProfile,graphResearch} from '../services/graph.ts'
import type {AuthorProfile} from '../services/graph.ts'
import {researchResultQuery} from '../services/research-navigation.ts'

const route = useRoute()
const router = useRouter()
const authorId = computed(()=>String(route.params.id??''))
const requestedBatch = computed(()=>typeof route.query.batch_id==='string'?route.query.batch_id:'')
const page = computed(()=>Math.max(1,Math.min(100000,parseInt(String(route.query.profile_page??'1'),10)||1)))
const retry = ref(0)
const loading = ref(true)
const error = ref('')
const profile = ref<AuthorProfile|null>(null)
const drawer = ref<string|null>(null)
const showGraph = ref(false)
const pageCount = computed(()=>profile.value?Math.max(1,Math.ceil(profile.value.papers.total/profile.value.papers.page_size)):1)
const backLocation = computed(()=>({
  path:'/research/papers',
  query:{...researchResultQuery(route.query),tab:'entities',kind:'author',
    batch_id:profile.value?.batch_id||requestedBatch.value||undefined},
}))
const charts = computed(()=>{
  const stats = profile.value?.statistics
  if(!stats)return []
  return [
    {title:'年份分布',field:'year',truncated:false,items:stats.years.map(item=>({
      id:String(item.year),name:String(item.year),paper_count:item.paper_count,
    }))},
    {title:'主题分布',field:'topic',...stats.distributions.topic},
    {title:'方法分布',field:'method',...stats.distributions.method},
  ] as const
})

watch([authorId,requestedBatch],()=>{
  drawer.value = null
  showGraph.value = false
})
watch([authorId,requestedBatch,page,retry],async ([id,batch,currentPage],previous,onCleanup)=>{
  const current = profile.value
  if(current?.author.id===id&&current.batch_id===batch&&current.papers.page===currentPage
    &&previous?.[3]===retry.value)return
  const controller = new AbortController()
  onCleanup(()=>controller.abort())
  const signal = AbortSignal.any([controller.signal,AbortSignal.timeout(45000)])
  loading.value = true
  error.value = ''
  try{
    const fixedBatch = batch||(await graphResearch.getDetail(id,signal,undefined,'authors')).batch_id
    const result = await getAuthorProfile(id,fixedBatch,currentPage,signal)
    if(controller.signal.aborted)return
    profile.value = result
    loading.value = false
    if(!batch)await router.replace({query:{...route.query,batch_id:fixedBatch}})
  }catch(cause){
    if(!controller.signal.aborted){
      profile.value = null
      error.value = cause instanceof Error?cause.message:'读取作者画像失败。'
    }
  }finally{
    if(!controller.signal.aborted)loading.value = false
  }
},{immediate:true})

function paperList(field?:'year'|'topic'|'method',value?:string){
  const query:Record<string,string> = {tab:'papers',author_id:authorId.value,batch_id:profile.value?.batch_id??''}
  if(field&&value)query[field] = value
  return {path:'/research/papers',query}
}
function goToPage(value:number){
  void router.replace({query:{...route.query,profile_page:String(value)}})
}
function barWidth(count:number){
  return 100*count/(profile.value?.papers.total||1)+'%'
}
function paperLabel(id:string){
  const paper = profile.value?.papers.items.find(item=>item.id===id)
  return paper?.title??paper?.name??id.split('/').at(-1)??id
}
function explore(seed:string){
  void router.push({path:'/research/papers',query:{...backLocation.value.query,seed}})
}
</script>

<template>
  <section class="standard-page author-profile">
    <header class="page-heading">
      <div><div class="eyebrow">作者证据画像</div><h1>{{profile?.author.name??'作者画像'}}</h1>
        <p>按稳定作者 ID 统计整个发布批次中的关联论文。</p></div>
      <RouterLink class="button button-secondary" :to="backLocation">返回作者检索</RouterLink>
    </header>
    <StatePanel v-if="loading" kind="loading" title="正在读取作者画像"/>
    <StatePanel v-else-if="error" kind="error" title="作者画像暂不可用" :description="error" retry @retry="retry++"/>
    <template v-else-if="profile">
      <div class="identity">
        <span>作者 ID <code>{{profile.author.id}}</code></span>
        <span>发布批次 <code>{{profile.batch_id}}</code></span>
        <span v-if="profile.identity.same_name_other_ids">本批次另有 {{profile.identity.same_name_other_ids}} 个同名作者 ID，已分别统计。</span>
      </div>
      <div class="profile-grid metrics">
        <RouterLink class="panel card" :to="paperList()">
          <span>本批次累计论文</span><strong>{{profile.papers.total}}</strong><small>查看全部关联论文 ↗</small>
        </RouterLink>
        <div class="panel card"><span>覆盖年份</span><strong>{{profile.statistics.years.length}}</strong><small>根据本批次已收录论文</small></div>
        <div class="panel card"><span>有论文证据的机构</span><strong>{{profile.institutions.length}}</strong><small>按机构 ID 统计</small></div>
      </div>

      <div class="profile-grid charts">
        <section v-for="chart in charts" :key="chart.field" class="panel card">
          <h2>{{chart.title}}</h2>
          <p v-if="!chart.items.length" class="small-note">当前批次没有相关记录。</p>
          <p v-else-if="chart.truncated" class="small-note">按关联论文数展示前 8 项。</p>
          <RouterLink v-for="item in chart.items" :key="item.id" :to="paperList(chart.field,item.id)" class="chart-row">
            <span>{{item.name}}</span><span class="track" aria-hidden="true"><span :style="{width:barWidth(item.paper_count)}"></span></span>
            <span>{{item.paper_count}} 篇 ↗</span>
          </RouterLink>
        </section>
      </div>
      <p class="small-note chart-note">图表按论文去重，同篇论文可进入多个标签。主题和方法图表基于图谱中的提及关系。</p>

      <section class="panel card">
        <h2>机构关联证据</h2>
        <p class="small-note">每项关联都可回到对应论文核对署名机构记录。</p>
        <p v-if="!profile.institutions.length" class="small-note">当前批次没有可核对的机构关联。</p>
        <details v-for="institution in profile.institutions" :key="institution.id" class="profile-row">
          <summary>{{institution.name}} · {{institution.paper_ids.length}} 篇有证据的论文</summary>
          <div class="actions proof-links">
            <button v-for="id in institution.paper_ids" :key="id" type="button" class="text-button" @click="drawer=id">{{paperLabel(id)}}</button>
          </div>
        </details>
      </section>

      <section class="panel card">
        <h2>关联论文（{{profile.papers.total}} 篇）</h2>
        <p v-if="!profile.papers.items.length" class="small-note">本页没有论文。</p>
        <article v-for="paper in profile.papers.items" :key="paper.id" class="profile-row paper-row">
          <span>{{paper.year}} · {{paper.title??paper.name}}</span>
          <button type="button" class="text-button" @click="drawer=paper.id">查看证据</button>
        </article>
        <div v-if="pageCount>1" class="actions pagination">
          <button type="button" class="button button-secondary" :disabled="page<=1" @click="goToPage(page-1)">上一页</button>
          <span>{{page}} / {{pageCount}}</span>
          <button type="button" class="button button-secondary" :disabled="page>=pageCount" @click="goToPage(page+1)">下一页</button>
        </div>
      </section>

      <section class="panel card">
        <div class="actions"><h2>作者关联图谱</h2>
          <button type="button" class="button button-secondary" :aria-expanded="showGraph" @click="showGraph=!showGraph">{{showGraph?'收起图谱':'展开图谱'}}</button>
        </div>
        <CrossPaperGraph v-if="showGraph" :seed="profile.author.id" :batch="profile.batch_id" @select="id=>drawer=id"/>
      </section>
      <DetailDrawer :id="drawer" source="c" :batch-id="profile.batch_id" @close="drawer=null"
        @paper="id=>drawer=id" @navigate="id=>drawer=id" @explore="explore"/>
    </template>
  </section>
</template>

<style scoped>
.author-profile{padding-bottom:28px}
.identity{display:grid;gap:6px;margin-bottom:16px;color:#557177;font-size:12px;overflow-wrap:anywhere}
.profile-grid{display:grid;gap:12px}
.metrics{grid-template-columns:repeat(auto-fit,minmax(155px,1fr));margin-bottom:14px}
.metrics .card{display:flex;flex-direction:column;gap:5px;color:#375a62}
.metrics strong{font-size:28px;color:#236e61}
.metrics small{color:#557177}
.charts{grid-template-columns:repeat(auto-fit,minmax(min(100%,265px),1fr));align-items:start}
.card{padding:17px 18px;margin-bottom:12px}
.card h2{font-size:16px;margin-bottom:7px}
.chart-row{display:grid;grid-template-columns:minmax(50px,1fr) minmax(40px,1fr) max-content;align-items:center;gap:8px;padding:7px 4px;font-size:12px;color:#294b56;overflow-wrap:anywhere}
.chart-row:hover,.chart-row:focus-visible{background:#edf7f3}
.track{height:8px;background:#e8f1ef;border-radius:6px}
.track span{display:block;height:100%;background:#398c80;border-radius:6px}
.chart-note{margin-bottom:14px}
.profile-row{border-top:1px solid #e4eeeb;padding:10px 0;font-size:13px}
.profile-row summary{cursor:pointer}
.paper-row{display:flex;justify-content:space-between;gap:12px;min-height:0}
.actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.proof-links,.pagination{padding-top:10px}
</style>
