<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import StatePanel from '../components/StatePanel.vue'
import {getResearchStatistics} from '../services/graph.ts'
import type {ResearchStatistics} from '../services/graph.ts'

const route = useRoute()
const router = useRouter()
const statistics = ref<ResearchStatistics|null>(null)
const requestedBatch = computed(()=>typeof route.query.batch_id==='string'?route.query.batch_id:'')
const loading = ref(true)
const error = ref('')
const retry = ref(0)
const groups = [{kind:'topic',label:'主题分布'},{kind:'method',label:'方法分布'}] as const

watch([requestedBatch,retry],async ([batch,attempt],previous,onCleanup)=>{
  if(batch&&statistics.value?.batch_id===batch&&previous?.[1]===attempt)return
  const controller = new AbortController()
  onCleanup(()=>controller.abort())
  const signal = AbortSignal.any([controller.signal,AbortSignal.timeout(45000)])
  loading.value = true
  error.value = ''
  statistics.value = null
  try{
    const data = await getResearchStatistics(batch,signal)
    if(controller.signal.aborted)return
    statistics.value = data
    loading.value = false
    if(!batch)await router.replace({query:{...route.query,batch_id:data.batch_id}})
  }catch(cause){
    if(!controller.signal.aborted)error.value = cause instanceof Error?cause.message:'读取研究统计失败。'
  }finally{
    if(!controller.signal.aborted)loading.value = false
  }
},{immediate:true})

function latest(){
  if(requestedBatch.value)void router.replace({query:{...route.query,batch_id:undefined}})
  else retry.value++
}
function papersBy(field?:'year'|'topic'|'method',value?:string){
  const query:Record<string,string> = {tab:'papers',batch_id:statistics.value!.batch_id}
  if(field&&value)query[field] = value
  return {path:'/research/papers',query}
}
function ratio(count:number){
  const total = statistics.value?.paper_count||1
  return Math.min(100,Math.max(0,100*count/total))
}
</script>

<template>
  <section class="standard-page analytics-page">
    <header class="page-heading">
      <div>
        <div class="eyebrow">研究分析</div>
        <h1>研究分析看板</h1>
        <p>查看当前批次的论文分布，点击图表下钻到同批论文、证据和关联图谱。</p>
      </div>
      <button class="button button-secondary" type="button" :disabled="loading" @click="latest">读取最新发布</button>
    </header>
    <StatePanel v-if="loading" kind="loading" title="正在读取图谱统计"/>
    <StatePanel v-else-if="error" kind="error" title="研究统计暂不可用" :description="error" retry @retry="retry++"/>
    <template v-else-if="statistics">
      <div class="metrics">
        <RouterLink class="panel metric" :to="papersBy()">
          <span>论文总数</span><strong>{{statistics.paper_count}}</strong><small>查看本批全部论文 ↗</small>
        </RouterLink>
        <div v-for="group in groups" :key="group.kind" class="panel metric">
          <span>{{group.kind==='topic'?'有主题关联的论文':'有方法关联的论文'}}</span>
          <strong>{{statistics.distributions[group.kind].papers_with_effective_relation}}</strong>
          <small>占本批次 {{ratio(statistics.distributions[group.kind].papers_with_effective_relation).toFixed(1)}}%</small>
        </div>
      </div>
      <p class="scope">
        发布批次 <code>{{statistics.batch_id}}</code><br>
        统计口径：同一标签下按论文去重，同篇论文可进入多个标签。关系表示论文提及，具体含义可打开原文证据核对。
      </p>
      <section class="panel chart year-chart">
        <h2>年份分布</h2>
        <p v-if="statistics.years.length===1" class="chart-note">当前批次仅覆盖 {{statistics.years[0]?.year}} 年。</p>
        <p v-else-if="!statistics.years.length" class="chart-note">当前批次没有可统计的论文。</p>
        <RouterLink v-for="item in statistics.years" :key="item.year" :to="papersBy('year',String(item.year))" class="bar-row">
          <span class="bar-label">{{item.year}}</span>
          <span class="track" aria-hidden="true"><span class="bar" :style="{width:ratio(item.paper_count)+'%'}"></span></span>
          <span class="bar-count">{{item.paper_count}} 篇 ↗</span>
        </RouterLink>
      </section>
      <div class="charts">
        <section v-for="group in groups" :key="group.kind" class="panel chart" :class="group.kind">
          <h2>{{group.label}}</h2>
          <p class="chart-note" v-if="!statistics.distributions[group.kind].items.length">当前批次没有可统计的关联。</p>
          <p class="chart-note" v-else-if="statistics.distributions[group.kind].truncated">按关联论文数展示前 12 项。</p>
          <RouterLink v-for="item in statistics.distributions[group.kind].items" :key="item.id"
            :to="papersBy(group.kind,item.id)" class="bar-row">
            <span class="bar-label" :title="item.name">{{item.name}}</span>
            <span class="track" aria-hidden="true"><span class="bar" :style="{width:ratio(item.paper_count)+'%'}"></span></span>
            <span class="bar-count">{{item.paper_count}} 篇 ↗</span>
          </RouterLink>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.analytics-page{padding-bottom:26px}
.metrics,.charts{display:grid;gap:14px}
.metrics{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.charts{grid-template-columns:repeat(auto-fit,minmax(min(100%,365px),1fr));align-items:start}
.metric{padding:18px 20px;display:flex;flex-direction:column;gap:5px;color:#385963;font-size:13px}
a.metric:hover{border-color:#75a99b;background:#f4faf7}
.metric strong{font-size:31px;color:#1d6058}
.metric small,.scope,.chart-note{color:#557177;line-height:1.75}
.scope{font-size:13px;margin:14px 0;overflow-wrap:anywhere}
.chart{padding:18px 20px}
.chart h2{font-size:16px;margin-bottom:8px}
.chart-note{font-size:12px;margin-bottom:7px}
.year-chart{margin-bottom:14px}
.bar-row{display:grid;grid-template-columns:minmax(72px,1fr) minmax(52px,1.1fr) max-content;align-items:center;gap:9px;color:#294b56;padding:8px 4px;border-radius:6px;font-size:13px}
.bar-row:hover,.bar-row:focus-visible{background:#eef7f4}
.bar-label{overflow-wrap:anywhere}
.bar-count{font-variant-numeric:tabular-nums}
.track{height:10px;background:#edf3f1;border-radius:6px}
.bar{height:100%;display:block;background:#3b9483;border-radius:6px}
.method .bar{background:#5779ae}
.topic .bar{background:#b37b3b}
</style>
