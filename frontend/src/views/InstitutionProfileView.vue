<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import CrossPaperGraph from '../components/CrossPaperGraph.vue'
import DetailDrawer from '../components/DetailDrawer.vue'
import DistributionDonut from '../components/DistributionDonut.vue'
import StatePanel from '../components/StatePanel.vue'
import {getInstitutionProfile} from '../services/graph.ts'
import type {InstitutionProfile} from '../services/graph.ts'
import {researchResultQuery} from '../services/research-navigation.ts'

const route=useRoute(),router=useRouter()
const institutionId=computed(()=>String(route.params.id??''))
const requestedBatch=computed(()=>typeof route.query.batch_id==='string'?route.query.batch_id:'')
const page=computed(()=>Math.max(1,Math.min(100000,parseInt(String(route.query.profile_page??'1'),10)||1)))
const profile=ref<InstitutionProfile|null>(null)
const loading=ref(true),error=ref(''),retry=ref(0),drawer=ref<string|null>(null),showGraph=ref(false)
const pageCount=computed(()=>profile.value?Math.max(1,Math.ceil(profile.value.papers.total/profile.value.papers.page_size)):1)
const backLocation=computed(()=>(
  {path:'/research/papers',query:{...researchResultQuery(route.query),tab:'entities',kind:'institution',
    batch_id:profile.value?.batch_id||requestedBatch.value||undefined}}
))
const yearRange=computed(()=>{
  const years=profile.value?.statistics.years.map(item=>item.year).filter(Boolean)??[]
  if(!years.length)return '未知'
  const min=Math.min(...years),max=Math.max(...years)
  return min===max?String(min):`${min}—${max}`
})
const trend=computed(()=>{
  const items=[...(profile.value?.statistics.years??[])].sort((a,b)=>a.year-b.year)
  const width=720,height=230,left=50,right=20,top=22,bottom=44
  const max=Math.max(1,...items.map(item=>item.paper_count))
  const points=items.map((item,index)=>({
    ...item,
    x:items.length===1?(left+width-right)/2:left+index*(width-left-right)/(items.length-1),
    y:top+(max-item.paper_count)*(height-top-bottom)/max,
    showLabel:items.length<=10||index===0||index===items.length-1||index%Math.ceil(items.length/8)===0,
  }))
  const line=points.map(point=>`${point.x},${point.y}`).join(' ')
  const area=points.length?`M ${points[0]!.x} ${height-bottom} L ${points.map(point=>`${point.x} ${point.y}`).join(' L ')} L ${points.at(-1)!.x} ${height-bottom} Z`:''
  return {items,points,line,area,width,height,left,right,top,bottom,max}
})

watch([institutionId,requestedBatch],()=>{drawer.value=null;showGraph.value=false})
watch([institutionId,requestedBatch,page,retry],async ([id,batch,currentPage],_,onCleanup)=>{
  const controller=new AbortController();onCleanup(()=>controller.abort())
  loading.value=true;error.value=''
  try{
    const result=await getInstitutionProfile(id,batch,currentPage,AbortSignal.any([controller.signal,AbortSignal.timeout(45000)]))
    if(controller.signal.aborted)return
    profile.value=result
    if(!batch)await router.replace({query:{...route.query,batch_id:result.batch_id}})
  }catch(cause){
    if(!controller.signal.aborted){profile.value=null;error.value=cause instanceof Error?cause.message:'读取机构画像失败。'}
  }finally{if(!controller.signal.aborted)loading.value=false}
},{immediate:true})

function papersBy(field?:'year'|'topic'|'method'|'direction',value?:string){
  const query:Record<string,string>={tab:'papers',institution:institutionId.value,batch_id:profile.value?.batch_id??''}
  if(field&&value)query[field]=value
  return {path:'/research/papers',query}
}
function goToPage(value:number){void router.replace({query:{...route.query,profile_page:String(value)}})}
function openDistribution(field:'topic'|'method'|'direction',id:string){void router.push(papersBy(field,id))}
function explore(seed:string){void router.push({path:'/research/papers',query:{...papersBy().query,seed,seed_label:profile.value?.institution.name}})}
</script>

<template>
  <section class="standard-page institution-profile">
    <header class="page-heading">
      <div><div class="eyebrow">机构证据画像</div><h1>{{profile?.institution.name??'机构画像'}}</h1>
        <p>按稳定机构 ID 汇总同一发布批次中的论文、研究方向、主题、方法和证据关系。</p></div>
      <RouterLink class="button button-secondary" :to="backLocation">返回机构检索</RouterLink>
    </header>
    <StatePanel v-if="loading" kind="loading" title="正在生成机构画像"/>
    <StatePanel v-else-if="error" kind="error" title="机构画像暂不可用" :description="error" retry @retry="retry++"/>
    <template v-else-if="profile">
      <div class="identity">
        <span>机构 ID <code>{{profile.institution.id}}</code></span>
        <span>发布批次 <code>{{profile.batch_id}}</code></span>
        <span>统计只代表当前快照中有论文证据的关联，不推断永久任职或机构归属。</span>
      </div>

      <div class="metrics">
        <RouterLink class="panel metric" :to="papersBy()"><span>关联论文</span><strong>{{profile.papers.total}}</strong><small>查看同批论文与证据 ↗</small></RouterLink>
        <div class="panel metric"><span>覆盖年份</span><strong>{{profile.statistics.years.length}}</strong><small>{{yearRange}}</small></div>
        <div class="panel metric"><span>研究方向</span><strong>{{profile.statistics.distributions.research_direction.items.length}}{{profile.statistics.distributions.research_direction.truncated?'＋':''}}</strong><small>{{profile.statistics.distributions.research_direction.truncated?'当前展示前列方向':'来自 B 的来源分类'}}</small></div>
        <div class="panel metric"><span>有证据作者</span><strong>{{profile.authors.length}}{{profile.detail.truncated?'＋':''}}</strong><small>{{profile.detail.truncated?'详情已截断，至少为该数量':'按稳定作者 ID 去重'}}</small></div>
      </div>

      <section class="panel trend-card">
        <header><div><h2>论文年份发展趋势</h2><p>按论文年份统计当前发布批次中的关联论文。</p></div><strong>{{yearRange}}</strong></header>
        <p v-if="!trend.items.length" class="small-note">当前机构没有可统计的论文年份。</p>
        <svg v-else :viewBox="`0 0 ${trend.width} ${trend.height}`" role="img" aria-label="机构论文年份发展趋势折线图">
          <defs><linearGradient id="institution-trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4b9b8b" stop-opacity=".34"/><stop offset="1" stop-color="#4b9b8b" stop-opacity=".03"/></linearGradient></defs>
          <line :x1="trend.left" :x2="trend.width-trend.right" :y1="trend.top" :y2="trend.top" class="grid-line"/>
          <line :x1="trend.left" :x2="trend.width-trend.right" :y1="(trend.top+trend.height-trend.bottom)/2" :y2="(trend.top+trend.height-trend.bottom)/2" class="grid-line"/>
          <line :x1="trend.left" :x2="trend.width-trend.right" :y1="trend.height-trend.bottom" :y2="trend.height-trend.bottom" class="axis-line"/>
          <text x="8" :y="trend.top+4">{{trend.max}}</text><text x="18" :y="trend.height-trend.bottom+4">0</text>
          <path :d="trend.area" fill="url(#institution-trend-fill)"/><polyline :points="trend.line" class="trend-line"/>
          <g v-for="point in trend.points" :key="point.year">
            <RouterLink :to="papersBy('year',String(point.year))">
              <circle :cx="point.x" :cy="point.y" r="6"><title>{{point.year}}：{{point.paper_count}} 篇，点击查看论文</title></circle>
              <text :x="point.x" :y="point.y-12" text-anchor="middle" class="count-label">{{point.paper_count}}</text>
            </RouterLink>
            <text v-if="point.showLabel" :x="point.x" :y="trend.height-17" text-anchor="middle">{{point.year}}</text>
          </g>
        </svg>
      </section>

      <div class="distribution-grid">
        <DistributionDonut title="研究方向占比" :items="profile.statistics.distributions.research_direction.items" :paper-total="profile.papers.total" @select="openDistribution('direction',$event)"/>
        <DistributionDonut title="研究主题占比" :items="profile.statistics.distributions.topic.items" :paper-total="profile.papers.total" @select="openDistribution('topic',$event)"/>
        <DistributionDonut title="研究方法占比" :items="profile.statistics.distributions.method.items" :paper-total="profile.papers.total" @select="openDistribution('method',$event)"/>
      </div>

      <section class="panel card authors-card">
        <h2>有证据的关联作者</h2><p class="small-note">仅展示当前批次中通过论文署名关系连接到该机构的作者；点击可继续查看作者画像。</p>
        <p v-if="!profile.authors.length" class="small-note">当前批次没有可展示的作者关系。</p>
        <div v-else class="author-cloud">
          <RouterLink v-for="author in profile.authors" :key="author.id" :to="{path:'/research/authors/'+encodeURIComponent(author.id),query:{batch_id:profile.batch_id}}">{{author.name}}</RouterLink>
        </div>
      </section>

      <section class="panel card">
        <div class="section-heading"><div><h2>关联论文（{{profile.papers.total}} 篇）</h2><p class="small-note">列表、趋势和占比图均固定在同一发布批次。</p></div><RouterLink class="text-button" :to="papersBy()">进入完整检索 ↗</RouterLink></div>
        <p v-if="!profile.papers.items.length" class="small-note">本页没有论文。</p>
        <article v-for="paper in profile.papers.items" :key="paper.id" class="paper-row">
          <div><strong>{{paper.title}}</strong><small>{{paper.year||'年份未知'}} · {{paper.venue||'会议未知'}} · {{paper.authors.length?paper.authors.join('、'):'作者未知'}}</small></div>
          <button type="button" class="text-button" @click="drawer=paper.id">查看知识与证据</button>
        </article>
        <div v-if="pageCount>1" class="pagination">
          <button type="button" class="button button-secondary" :disabled="page<=1" @click="goToPage(page-1)">上一页</button><span>{{page}} / {{pageCount}}</span>
          <button type="button" class="button button-secondary" :disabled="page>=pageCount" @click="goToPage(page+1)">下一页</button>
        </div>
      </section>

      <section class="panel card">
        <div class="section-heading"><div><h2>机构关联图谱</h2><p class="small-note">继续使用 C 的一跳／两跳查询和证据，统一由 D 的图谱组件渲染。</p></div>
          <button type="button" class="button button-secondary" :aria-expanded="showGraph" @click="showGraph=!showGraph">{{showGraph?'收起图谱':'展开图谱'}}</button></div>
        <CrossPaperGraph v-if="showGraph" :seed="profile.institution.id" :batch="profile.batch_id" @select="id=>drawer=id"/>
      </section>
      <DetailDrawer :id="drawer" source="c" :batch-id="profile.batch_id" @close="drawer=null" @paper="id=>drawer=id" @navigate="id=>drawer=id" @explore="explore"/>
    </template>
  </section>
</template>

<style scoped>
.institution-profile{padding-bottom:30px}.identity{display:grid;gap:6px;margin-bottom:16px;color:#557177;font-size:12px;overflow-wrap:anywhere}
.metrics,.distribution-grid{display:grid;gap:13px}.metrics{grid-template-columns:repeat(auto-fit,minmax(165px,1fr));margin-bottom:14px}.metric{padding:18px 20px;display:flex;flex-direction:column;gap:5px;color:#375a62}.metric strong{font-size:30px;color:#236e61}.metric small{color:#607a82;font-size:11px;line-height:1.5}a.metric:hover{background:#f3faf7;border-color:#8bb8ad}
.trend-card{padding:18px 20px;margin-bottom:14px}.trend-card header,.section-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}.trend-card h2,.card h2{font-size:16px;margin-bottom:5px}.trend-card header p{font-size:12px;color:#617a82}.trend-card header>strong{font-size:13px;color:#2f756b}.trend-card svg{display:block;width:100%;max-height:290px;margin-top:6px;overflow:visible}.trend-card text{font:11px Microsoft YaHei,sans-serif;fill:#6a8188}.trend-card .count-label{fill:#2b6f65;font-weight:700}.grid-line{stroke:#dfeae7;stroke-dasharray:4 5}.axis-line{stroke:#b6cbc5}.trend-line{fill:none;stroke:#2e8879;stroke-width:4;stroke-linecap:round;stroke-linejoin:round}.trend-card circle{fill:#fbfdfd;stroke:#2e8879;stroke-width:4;cursor:pointer}.trend-card circle:hover{r:8;fill:#dff1eb}
.distribution-grid{grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));align-items:start;margin-bottom:14px}.card{padding:18px 20px;margin-bottom:14px}.author-cloud{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.author-cloud a{padding:6px 10px;border-radius:999px;background:#edf5f3;color:#2e6d64;font-size:12px}.author-cloud a:hover{background:#dceee9}
.paper-row{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:12px 0;border-top:1px solid #e4edeb}.paper-row div{min-width:0}.paper-row strong{display:block;font-size:13px;line-height:1.6}.paper-row small{display:block;color:#607a82;font-size:11px;line-height:1.7;margin-top:3px}.pagination{display:flex;align-items:center;justify-content:center;gap:12px;padding-top:16px}
@media(max-width:700px){.trend-card header,.section-heading,.paper-row{flex-direction:column;align-items:stretch}.trend-card svg{min-height:210px}.paper-row .text-button{align-self:flex-start}}
</style>
