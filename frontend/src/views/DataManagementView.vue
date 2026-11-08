<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import AppIcon from '../components/AppIcon.vue'
import StatePanel from '../components/StatePanel.vue'
import {getDatasets,getJob,getJobPapers,getJobs,importDataset,retryJob,type DatasetInfo,type JobInfo} from '../services/admin.ts'

const route=useRoute(),router=useRouter()
const datasets=ref<DatasetInfo[]>([]),jobs=ref<JobInfo[]>([]),job=ref<JobInfo|null>(null),papers=ref<Record<string,any>[]>([])
const loading=ref(false),working=ref(false),error=ref(''),notice=ref(''),datasetId=ref('')
const mode=computed(()=>route.path.includes('/datasets')?'datasets':route.path.includes('/imports')?'imports':'jobs')
const selectedId=computed(()=>Number(route.query.job_id)||0)

async function load(){
  loading.value=true;error.value=''
  try{
    ;[datasets.value,jobs.value]=await Promise.all([getDatasets(),getJobs()])
    if(!datasetId.value)datasetId.value=datasets.value[0]?.id??''
    if(selectedId.value)await loadJob(selectedId.value)
  }catch(e){error.value=e instanceof Error?e.message:'无法读取 A 数据服务'}
  finally{loading.value=false}
}
async function loadJob(id:number){
  error.value=''
  try{
    const [nextJob,nextPapers]=await Promise.all([getJob(id),getJobPapers(id)])
    if(id!==selectedId.value)return
    job.value=nextJob;papers.value=nextPapers
  }catch(e){if(id===selectedId.value){job.value=null;papers.value=[];error.value=e instanceof Error?e.message:'无法读取任务详情'}}
}
async function choose(id:number){await router.replace({path:'/admin/jobs',query:{job_id:String(id)}})}
async function createImport(){
  if(!datasetId.value)return
  working.value=true;error.value='';notice.value=''
  try{const created=await importDataset(datasetId.value);notice.value=`已创建导入任务 #${created.id}，批次 ${created.batch_code}`;await router.push({path:'/admin/jobs',query:{job_id:String(created.id)}});await load()}
  catch(e){error.value=e instanceof Error?e.message:'创建导入失败'}finally{working.value=false}
}
async function retry(){
  if(!job.value)return
  working.value=true;error.value=''
  try{await retryJob(job.value.id);notice.value=`任务 #${job.value.id} 已提交重试，继续使用原批次。`;await load()}
  catch(e){error.value=e instanceof Error?e.message:'重试失败'}finally{working.value=false}
}
watch(selectedId,id=>{if(id)void loadJob(id);else{job.value=null;papers.value=[]}})
onMounted(load)
</script>

<template>
  <section class="standard-page data-page">
    <div class="page-heading"><div><div class="eyebrow">A · DATA PIPELINE 0.3.0</div><h1>数据与批次管理</h1><p>D 使用 Cookie 会话保护页面，由后端安全转发到 A 的管理接口。</p></div><button class="button button-secondary" @click="load"><AppIcon name="refresh"/>刷新</button></div>
    <div v-if="notice" class="inline-success"><AppIcon name="check"/>{{notice}}</div>
    <StatePanel v-if="loading" kind="loading" title="正在读取 A 数据服务"/>
    <StatePanel v-else-if="error" kind="error" title="A 接口调用失败" :description="error" retry @retry="load"/>
    <template v-else>
      <section v-if="mode==='datasets'" class="panel data-card">
        <header><h2>固定基准清单</h2><small>{{datasets.length}} 个可用数据集</small></header>
        <div v-if="datasets.length" class="dataset-grid"><article v-for="item in datasets" :key="item.id"><span class="badge badge-teal">{{item.id}}</span><h3>{{item.title}}</h3><p>{{item.venue||'来源由 A 校验'}} · {{item.year||'年度见清单'}} · {{item.paper_count??'未提供'}} 篇</p><small v-if="item.checksum" class="mono">{{item.checksum}}</small></article></div>
        <StatePanel v-else kind="empty" title="A 未返回基准清单"/>
      </section>
      <section v-else-if="mode==='imports'" class="panel data-card import-card">
        <header><h2>创建固定样本导入</h2><small>每次新导入创建新 Job；失败重试复用原批次</small></header>
        <label class="form-label">选择已校验基准</label><select v-model="datasetId" class="form-input"><option v-for="item in datasets" :key="item.id" :value="item.id">{{item.title}}（{{item.id}}）</option></select>
        <button class="button button-primary" :disabled="working||!datasetId" @click="createImport">{{working?'正在创建…':'创建导入任务'}}</button>
      </section>
      <div v-else class="job-layout">
        <section class="panel data-card"><header><h2>导入任务</h2><small>{{jobs.length}} 条任务</small></header><div class="job-list"><button v-for="item in jobs" :key="item.id" :class="{active:item.id===selectedId}" @click="choose(item.id)"><strong>#{{item.id}} · {{item.batch_code}}</strong><span>{{item.status}} / {{item.stage}}</span><small>成功 {{item.succeeded}} · 失败 {{item.failed}}</small></button></div><StatePanel v-if="!jobs.length" kind="empty" title="暂无任务"/></section>
        <section class="panel data-card"><template v-if="job"><header><h2>任务 #{{job.id}}</h2><span class="badge badge-teal">{{job.status}}</span></header><dl class="definition-list"><dt>批次</dt><dd>{{job.batch_code}}（ID {{job.batch_id}}）</dd><dt>数据集</dt><dd>{{job.dataset_id||'—'}}</dd><dt>阶段</dt><dd>{{job.stage}}</dd><dt>计数</dt><dd>尝试 {{job.attempted}} / 成功 {{job.succeeded}} / 失败 {{job.failed}}</dd><dt>错误</dt><dd>{{job.error||'无'}}</dd></dl><button v-if="job.status==='failed'||job.status==='partial'" class="button button-secondary" :disabled="working" @click="retry">重试原批次</button><h3 v-if="job.events?.length" class="paper-heading">任务日志</h3><div v-if="job.events?.length" class="job-events"><article v-for="event in job.events" :key="event.created_at+event.message"><span>{{event.level}} · {{event.stage}}</span><p>{{event.message}}</p></article></div><h3 class="paper-heading">批次论文（{{papers.length}}）</h3><div class="batch-papers"><article v-for="paper in papers" :key="String(paper.id)"><strong>{{paper.title||`论文 ${paper.id}`}}</strong><small>{{paper.year||'—'}} · {{paper.venue||paper.source||'来源见详情'}}</small></article></div></template><StatePanel v-else kind="empty" title="请选择一个任务" description="查看计数、错误和批次论文。"/></section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.data-page{padding-bottom:30px}.data-card{padding:24px}.data-card>header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #edf2f4;padding-bottom:17px;margin-bottom:20px}.data-card header small{color:#93a6af;font-size:11px}.dataset-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.dataset-grid article{border:1px solid #e6edef;border-radius:9px;padding:17px}.dataset-grid h3{margin:14px 0 8px}.dataset-grid p,.dataset-grid small{font-size:11px;color:#8298a3;line-height:1.8}.import-card{max-width:650px}.import-card .button{margin-top:20px}.job-layout{display:grid;grid-template-columns:minmax(280px,.75fr) minmax(420px,1.25fr);gap:20px}.job-list{display:flex;flex-direction:column;gap:8px}.job-list button{border:1px solid #e5edef;background:#fff;border-radius:7px;padding:13px;text-align:left;display:flex;flex-direction:column;gap:6px}.job-list button.active{border-color:#8bc8ba;background:#f0f8f6}.job-list strong{font-size:12px}.job-list span,.job-list small{font-size:10px;color:#8096a0}.paper-heading{margin:25px 0 12px}.batch-papers{max-height:270px;overflow:auto}.batch-papers article{display:flex;flex-direction:column;gap:5px;padding:10px 0;border-bottom:1px solid #edf2f4}.batch-papers strong{font-size:11px}.batch-papers small{font-size:10px;color:#91a3ac}.job-events{border-left:2px solid #dce9e6;padding-left:12px}.job-events article{margin:10px 0}.job-events span{font-size:9px;color:#4d9584;text-transform:uppercase}.job-events p{font-size:10px;color:#7f949e;line-height:1.7;margin-top:3px}@media(max-width:900px){.job-layout{grid-template-columns:1fr}}
</style>
