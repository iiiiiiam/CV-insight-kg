<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {RouterLink,useRoute,useRouter} from 'vue-router'
import StatePanel from '../components/StatePanel.vue'
import BatchComparison from '../components/BatchComparison.vue'
import {batchCode,importProgress} from '../services/import-progress.ts'
import {getDatasets,getReserve,importReserve,getSources,getJob,getJobs,getBatchPapers,getHandoff,retryJob,type ReserveLibrary,type DatasetInfo,type JobInfo} from '../services/admin.ts'

const route=useRoute(),router=useRouter()
const datasets=ref<DatasetInfo[]>([]),jobs=ref<JobInfo[]>([]),job=ref<JobInfo|null>(null),papers=ref<Record<string,any>[]>([])
const loading=ref(false),working=ref(false),error=ref(''),notice=ref('')
const query=ref(''),paperPage=ref(1),paperTotal=ref(0),sourceFilter=ref(''),venueFilter=ref('')
const statusName=(s:string)=>({succeeded:'已完成',partial:'需处理',failed:'失败',queued:'等待中',running:'导入中'} as Record<string,string>)[s]??s
const sourceName=(s:string)=>({openalex:'OpenAlex',ecva:'ECVA',cvf:'CVF',dblp:'DBLP',auto:'自动'} as Record<string,string>)[s]??s
const visibleJobs=computed(()=>[...jobs.value].sort((a,b)=>b.id-a.id).filter(j=>(!sourceFilter.value||j.source===sourceFilter.value)&&(!venueFilter.value||j.venue===venueFilter.value)&&(route.query.view!=='errors'||['failed','partial'].includes(j.status))))
const sourceOptions=ref<Array<{name:string;enabled:boolean}>>([])
const reserve=ref<ReserveLibrary>({items:[],available:0}),reserveIndex=ref(0),reserveCount=ref(20)
const selectedReserve=computed(()=>reserve.value.items[reserveIndex.value])
const mode=computed(()=>route.path.includes('/datasets')?'datasets':route.path.includes('/imports')?'imports':'jobs')
const selectedId=computed(()=>Number(route.query.job_id)||0)
const backToImport=computed(()=>mode.value==='jobs'&&route.query.from==='imports')
const progress=computed(()=>job.value?importProgress(job.value):null)

async function load(){
  loading.value=true;error.value=''
  try{
    ;[datasets.value,jobs.value,sourceOptions.value,reserve.value]=await Promise.all([getDatasets(),getJobs(),getSources(),getReserve()])
    if(!selectedReserve.value?.available)reserveIndex.value=Math.max(0,reserve.value.items.findIndex(item=>item.available>0))
    if(selectedId.value)await loadJob(selectedId.value)
  }catch(e){error.value=e instanceof Error?e.message:'无法读取 A 数据服务'}
  finally{loading.value=false}
}
async function loadJob(id:number){
  error.value=''
  try{
    const [nextJob,nextPapers]=await Promise.all([getJob(id),getBatchPapers(id,paperPage.value,query.value)])
    if(id!==selectedId.value)return
    job.value=nextJob;papers.value=nextPapers.items;paperTotal.value=nextPapers.total
    jobs.value=jobs.value.map(item=>item.id===nextJob.id?nextJob:item)
  }catch(e){if(id===selectedId.value){job.value=null;papers.value=[];error.value=e instanceof Error?e.message:'无法读取任务详情'}}
}
async function choose(id:number){query.value="";paperPage.value=1;await router.replace({path:'/admin/jobs',query:{job_id:String(id),from:route.query.from==='imports'?'imports':undefined}})}
async function createReserve(){
  if(!selectedReserve.value)return
  working.value=true;error.value='';notice.value=''
  try{const created=await importReserve(selectedReserve.value,reserveCount.value);await router.push({path:'/admin/jobs',query:{job_id:String(created.id),from:'imports'}});await load()}
  catch(e){error.value=e instanceof Error?e.message:'补充论文导入失败'}finally{working.value=false}
}
watch(selectedReserve,item=>{if(item?.available&&reserveCount.value>item.available)reserveCount.value=Math.min(20,item.available)})
async function retry(){
  if(!job.value)return
  working.value=true;error.value=''
  try{await retryJob(job.value.id);notice.value=`任务 #${job.value.id} 已提交重试，继续使用原批次。`;await load()}
  catch(e){error.value=e instanceof Error?e.message:'重试失败'}finally{working.value=false}
}
async function exportPapers(){if(!job.value)return;working.value=true;error.value='';try{const data=await getHandoff(job.value.id);if(!data.exported_papers)throw new Error('该批次暂时没有可导出的完整论文');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`papers-${job.value.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice.value=`已导出 ${data.exported_papers} 篇，信息不完整 ${data.excluded_papers} 篇`}catch(e){error.value=e instanceof Error?e.message:'导出失败'}finally{working.value=false}}

watch(selectedId,id=>{if(id)void loadJob(id);else{job.value=null;papers.value=[]}})
let timer:ReturnType<typeof setInterval>|undefined
onMounted(()=>{void load();timer=setInterval(()=>{if(selectedId.value&&(!job.value||['queued','running'].includes(job.value.status))){void loadJob(selectedId.value)}},1500)})
onUnmounted(()=>{if(timer)clearInterval(timer)})
</script>


<template><section class="standard-page data-page"><div class="page-heading"><div><div class="eyebrow">DATA MANAGEMENT</div><h1>{{mode==='imports'?'论文导入':mode==='datasets'?'数据集':'导入记录'}}</h1><p>{{mode==='imports'?'选择补充论文范围和数量，分批导入新论文。':'查看导入批次、核对论文并处理失败任务。'}}</p></div><div class="page-actions"><RouterLink v-if="mode==='jobs'||mode==='imports'" class="button button-secondary" :to="backToImport?'/admin/imports':'/admin/overview'">{{backToImport?'← 返回论文导入':'← 返回数据概览'}}</RouterLink><button class="button button-secondary" @click="load">刷新</button></div></div>
<div v-if="notice" class="inline-success">{{notice}}</div><div v-if="error" class="inline-error">{{error}}</div><StatePanel v-if="loading" kind="loading" title="正在读取数据"/>
<template v-else><section v-if="mode==='datasets'" class="panel data-card"><header><h2>可用数据集</h2></header><div class="dataset-grid"><article v-for="item in datasets" :key="item.id"><h3>{{item.title}}</h3><p>{{item.venue}} {{item.year}} · {{item.paper_count}} 篇</p></article></div></section>
<div v-else-if="mode==='imports'" class="import-layout"><section class="panel data-card reserve-card"><header><h2>补充论文库</h2><small>待导入 {{reserve.available.toLocaleString('zh-CN')}} 篇</small></header><template v-if="reserve.items.length"><label class="form-label" for="reserve-scope">选择论文范围</label><select id="reserve-scope" v-model.number="reserveIndex" class="form-input"><option v-for="(item,i) in reserve.items" :key="`${item.venue}-${item.year}-${item.source}`" :value="i" :disabled="!item.available">{{item.venue}} {{item.year}} · {{sourceName(item.source)}} · 还可导入 {{item.available}} 篇</option></select><label class="form-label" for="reserve-count">本批导入数量</label><input id="reserve-count" v-model.number="reserveCount" type="number" min="1" :max="Math.min(100,selectedReserve?.available??100)" class="form-input"/><p class="hint">已排除入库论文。每次导入下一批新论文，完成后更新概览和最新论文列表。</p><button class="button button-primary" :disabled="working||!selectedReserve?.available||!Number.isInteger(reserveCount)||reserveCount<1||reserveCount>100||!sourceOptions.find(s=>s.name===selectedReserve.source)?.enabled" @click="createReserve">{{working?'正在提交…':'导入下一批'}}</button></template><p v-else class="hint">暂时没有待导入论文，请补充论文库后再试。</p></section></div>
<template v-else><section v-if="job?.kind==='reserve'&&progress" class="panel import-progress-card" aria-label="当前导入批次"><header><div><span class="eyebrow">CURRENT IMPORT</span><h2>{{batchCode(job)}}</h2><p>{{job.venue}} {{job.year}} · {{sourceName(job.source)}}</p></div><span class="progress-status" :class="job.status">{{progress.label}}</span></header><div class="progress-caption" aria-live="polite"><strong>{{progress.active?'正在处理':'已处理'}} {{progress.processed}} / {{progress.total}} 篇</strong><span>{{progress.percent}}%</span></div><div class="import-progress-track" role="progressbar" :aria-label="`${batchCode(job)} 导入进度`" :aria-valuenow="progress.percent" aria-valuemin="0" aria-valuemax="100"><i :style="{width:`${progress.percent}%`}" :class="job.status"/></div><div class="progress-totals"><span>成功 {{progress.succeeded}}</span><span>失败 {{progress.failed}}</span><span v-if="progress.skipped">过滤 {{progress.skipped}}</span><span v-if="job.status==='succeeded'">论文已保存到数据库</span></div><p v-if="job.error" class="inline-error">{{job.error}}</p></section><BatchComparison :jobs="jobs" :current-job-id="selectedId"/><section class="panel data-card"><div class="record-filters"><label>采集来源<select v-model="sourceFilter" class="form-input"><option value="">全部来源</option><option v-for="s in [...new Set(jobs.map(j=>j.source))]" :key="s" :value="s">{{sourceName(s)}}</option></select></label><label>会议<select v-model="venueFilter" class="form-input"><option value="">全部会议</option><option v-for="v in [...new Set(jobs.map(j=>j.venue))]" :key="v">{{v}}</option></select></label></div><div class="record-table"><table><thead><tr><th>批次编号</th><th>日期</th><th>来源</th><th>会议</th><th>处理数量</th><th>失败</th><th>状态</th><th/></tr></thead><tbody><tr v-for="item in visibleJobs" :key="item.id" :class="{selected:item.id===selectedId}"><td class="batch-code">{{batchCode(item)}}</td><td>{{item.created_at.slice(0,16).replace('T',' ')}}</td><td>{{sourceName(item.source)}}</td><td>{{item.venue}} {{item.year}}</td><td>{{item.attempted}}</td><td>{{item.failed}}</td><td>{{statusName(item.status)}}</td><td><button class="text-button" @click="choose(item.id)">查看详情</button></td></tr></tbody></table><p v-if="!visibleJobs.length" class="hint">没有符合条件的导入记录。</p></div></section>
<section v-if="job" class="panel data-card batch-detail"><header><h2>{{job.venue}} {{job.year}} · {{sourceName(job.source)}}</h2><span>{{statusName(job.status)}}</span></header><div class="batch-summary"><span>处理 <strong>{{job.attempted}}<template v-if="job.progress?.total"> / {{job.progress.total}}</template></strong></span><span>新增 <strong>{{(job as any).new_papers??'—'}}</strong></span><span>重复 <strong>{{(job as any).duplicate_papers??'—'}}</strong></span><span>失败 <strong>{{job.failed}}</strong></span><span v-if="(job as any).skipped">已过滤 <strong>{{(job as any).skipped}}</strong></span></div><p v-if="job.error" class="inline-error">{{job.error}}</p><p v-if="job.status==='partial'&&!job.failed" class="hint">本批次使用了保存的数据，请查看处理日志核对具体情况。</p><div class="batch-actions"><button v-if="job.status==='failed'||job.failed>0" class="button button-secondary" :disabled="working" @click="retry">重试失败任务</button><button class="button button-secondary" :disabled="working" @click="exportPapers">导出论文</button><RouterLink class="text-button" :to="{path:'/research/raw-papers',query:{batch_id:String(job.id)}}">在论文页面查看 →</RouterLink></div>
<section v-if="job.quality" class="quality-section"><h3>论文信息完整情况</h3><p class="hint">核对后续处理所需的信息，缺失内容不会自动补造。</p><div class="quality-grid"><article v-for="item in [{label:'含摘要',value:job.quality.with_abstract},{label:'含 DOI',value:job.quality.with_doi},{label:'含作者',value:job.quality.with_authors}]" :key="item.label"><span>{{item.label}}</span><strong>{{item.value}} / {{job.quality.total}} 篇</strong><small>{{job.quality.total-item.value}} 篇缺失</small></article></div></section>
<h3 class="paper-heading">批次论文 · {{paperTotal}} 篇</h3><form class="batch-actions" @submit.prevent="paperPage=1;loadJob(job.id)"><input v-model="query" class="form-input" placeholder="搜索本批论文标题或摘要" aria-label="搜索批次论文"/><button class="button button-secondary">搜索</button></form><div class="batch-papers"><article v-for="paper in papers" :key="paper.id"><strong>{{paper.title}}</strong><small>{{paper.venue}} {{paper.year}} · {{paper.authors?.join('、')||'作者信息暂缺'}}</small></article></div><div class="batch-actions"><button class="text-button" :disabled="paperPage<=1" @click="paperPage--;loadJob(job.id)">上一页</button><span>第 {{paperPage}} 页 / {{Math.max(1,Math.ceil(paperTotal/20))}} 页</span><button class="text-button" :disabled="paperPage*20>=paperTotal" @click="paperPage++;loadJob(job.id)">下一页</button></div><details v-if="job.events?.length" class="compare-detail"><summary>处理日志</summary><div class="job-events"><article v-for="event in job.events" :key="event.created_at+event.message"><p>{{event.message}}</p></article></div></details></section></template></template></section></template>

<style scoped>
.data-page{padding-bottom:30px}.data-card{padding:24px}.data-card>header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #edf2f4;padding-bottom:17px;margin-bottom:20px}.data-card header small{color:#93a6af;font-size:11px}.dataset-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.dataset-grid article{border:1px solid #e6edef;border-radius:9px;padding:17px}.dataset-grid h3{margin:14px 0 8px}.dataset-grid p,.dataset-grid small{font-size:11px;color:#8298a3;line-height:1.8}.import-card{max-width:650px}.import-card .button{margin-top:20px}.job-layout{display:grid;grid-template-columns:minmax(280px,.75fr) minmax(420px,1.25fr);gap:20px}.job-list{display:flex;flex-direction:column;gap:8px}.job-list button{border:1px solid #e5edef;background:#fff;border-radius:7px;padding:13px;text-align:left;display:flex;flex-direction:column;gap:6px}.job-list button.active{border-color:#8bc8ba;background:#f0f8f6}.job-list strong{font-size:12px}.job-list span,.job-list small{font-size:10px;color:#8096a0}.paper-heading{margin:25px 0 12px}.batch-papers{max-height:270px;overflow:auto}.batch-papers article{display:flex;flex-direction:column;gap:5px;padding:10px 0;border-bottom:1px solid #edf2f4}.batch-papers strong{font-size:11px}.batch-papers small{font-size:10px;color:#91a3ac}.job-events{border-left:2px solid #dce9e6;padding-left:12px}.job-events article{margin:10px 0}.job-events span{font-size:9px;color:#4d9584;text-transform:uppercase}.job-events p{font-size:10px;color:#7f949e;line-height:1.7;margin-top:3px}@media(max-width:900px){.job-layout{grid-template-columns:1fr}}
</style>

<style scoped>.import-layout{display:grid;grid-template-columns:minmax(0,1fr);width:100%;gap:20px}.hint{color:#789099;font-size:12px;line-height:1.8;margin:18px 0}.record-filters{display:flex;gap:16px;margin-bottom:20px}.record-filters label{font-size:12px;color:#6b858d}.record-table{overflow:auto}table{width:100%;border-collapse:collapse;font-size:12px;white-space:nowrap}th,td{text-align:left;padding:13px;border-bottom:1px solid #edf2f3}th{color:#769198;font-weight:500}tr.selected{background:#f0f8f5}.batch-detail{margin-top:20px}.batch-summary,.batch-actions{display:flex;gap:20px;align-items:center;flex-wrap:wrap;margin:20px 0;font-size:12px}.batch-summary strong{font-size:20px;margin-left:5px;color:#198e7d}.batch-actions .form-input{max-width:430px;flex:1;min-width:180px}.compare-detail{border-top:1px solid #e5edeb;padding:16px 0;font-size:12px;color:#66848b}.compare-detail summary{cursor:pointer}.compare-result p{margin:8px 0}@media(max-width:800px){.import-layout{grid-template-columns:1fr}.record-filters{flex-wrap:wrap}}</style>
<style scoped>.quality-section{padding:20px 0;border-top:1px solid #e5edeb}.quality-section h3{font-size:14px}.quality-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.quality-grid article{padding:16px;background:#f5f9f8;border-radius:8px;display:flex;flex-direction:column;gap:9px;font-size:12px;color:#68848b}.quality-grid strong{font-size:18px;color:#247e71}.quality-grid small{font-size:11px}@media(max-width:650px){.quality-grid{grid-template-columns:1fr}}</style>
<style scoped>.reserve-card{border-color:#beded5;background:linear-gradient(145deg,#fff,#f7fcfa)}.reserve-card .form-label{margin-top:16px;display:block}.reserve-card .form-input{width:100%}</style>

<style scoped>.page-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}</style>

<style scoped>
.import-progress-card{padding:24px;margin-bottom:20px}.import-progress-card header{display:flex;justify-content:space-between;align-items:center;gap:16px}.import-progress-card h2{font-size:20px;color:#355f68;margin:7px 0}.import-progress-card header p{font-size:12px;color:#80979f}.progress-status{padding:7px 13px;border-radius:20px;background:#edf5fa;color:#4b839e;font-size:12px}.progress-status.succeeded{background:#e7f5ee;color:#21826a}.progress-status.failed,.progress-status.partial{background:#fff0e9;color:#b36749}.progress-caption{display:flex;justify-content:space-between;align-items:center;margin:23px 0 10px;font-size:13px;color:#567a83}.import-progress-track{height:11px;background:#eaf1f1;border-radius:8px;overflow:hidden}.import-progress-track i{display:block;height:100%;background:#34a691;border-radius:8px;transition:width .3s}.import-progress-track i.failed,.import-progress-track i.partial{background:#c68a5c}.progress-totals{display:flex;flex-wrap:wrap;gap:20px;margin-top:14px;color:#7b949a;font-size:12px}.batch-code{font-weight:600;color:#398778}
</style>
