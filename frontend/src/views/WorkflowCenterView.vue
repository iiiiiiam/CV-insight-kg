<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import StatePanel from '../components/StatePanel.vue'
import {getHandoffSync,createReport,getBReportInput,getCReportInput,getPipeline,getTask,listTasks,reportDownloadUrl,reportFileUrl,retryTask,
  type PipelineState,type ReportSection,type WorkflowTask} from '../services/workflows.ts'

const route=useRoute(),router=useRouter()
const mode=computed<'reports'|'handoffs'>(()=>route.path.endsWith('/reports')?'reports':'handoffs')
const tasks=ref<WorkflowTask[]>([]),total=ref(0),detail=ref<WorkflowTask|null>(null),pipeline=ref<PipelineState|null>(null)
const sync=ref<Awaited<ReturnType<typeof getHandoffSync>>|null>(null)
const syncLabel=(state:string)=>({waiting:'等待对账',synchronized:'已对齐',repairing:'正在自动补交',attention:'需要核对',unavailable:'暂不可用'} as Record<string,string>)[state]??state
const summaryCount=(key:string)=>Array.isArray(sync.value?.summary[key])?(sync.value!.summary[key] as unknown[]).length:0
const syncIssues=computed(()=>{const rows=[...(Array.isArray(sync.value?.summary.conflicts)?sync.value!.summary.conflicts as Array<{batch_code:string;reason:string}>:[]),...(Array.isArray(sync.value?.summary.unverified)?sync.value!.summary.unverified as Array<{batch_code:string;reason:string}>:[])];return rows})
const loading=ref(true),working=ref(false),error=ref(''),notice=ref('')
const title=ref('本周论文数据报告'),reportMode=ref<'abc'|'ab'|'a'>('abc')
let timer:ReturnType<typeof setInterval>|undefined,generation=0,inFlight=0,pendingRequestKey=''

const selectedTaskId=computed(()=>typeof route.query.task_id==='string'?route.query.task_id:'')
const active=computed(()=>tasks.value.some(task=>['queued','running'].includes(task.status)||task.next_attempt_at)||['queued','running'].includes(detail.value?.status??''))
const taskStatus=(value:string)=>({queued:'等待处理',running:'处理中',succeeded:'已完成',failed:'失败'} as Record<string,string>)[value]??value
const stageStatus=(value:string)=>({succeeded:'已完成',processing:'处理中',running:'处理中',waiting:'等待',queued:'等待',changed:'版本已变化',unavailable:'暂不可用',failed:'失败'} as Record<string,string>)[value]??value
const date=(value:string|null)=>value?value.slice(0,16).replace('T',' '):'—'
const short=(value:string|null|undefined)=>value?value.slice(0,12)+'…':'—'
function makeKey(prefix:string){return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`}
function resultNumber(task:WorkflowTask,key:string){const value=task.result?.[key];return typeof value==='number'?value:null}
function resultText(task:WorkflowTask,key:string){const value=task.result?.[key];return typeof value==='string'?value:''}
function resultFiles(task:WorkflowTask){
  const files=task.result?.files
  return Array.isArray(files)?files.filter((item):item is {name:string;bytes:number;sha256:string}=>
    !!item&&typeof item==='object'&&typeof item.name==='string'&&typeof item.sha256==='string'):[]
}

async function load(showLoading=true){
  const current=++generation,identifier=selectedTaskId.value,taskMode=mode.value
  if(detail.value?.id!==identifier){detail.value=null;pipeline.value=null}
  inFlight++
  if(showLoading)loading.value=true
  error.value=''
  try{
    const taskList=await listTasks(mode.value,1)
    if(current!==generation)return
    tasks.value=taskList.items;total.value=taskList.total
    if(mode.value==='handoffs'){const value=await getHandoffSync();if(current!==generation)return;sync.value=value}
    if(identifier){
      const task=await getTask(taskMode,identifier)
      if(current!==generation)return
      detail.value=task
      if(taskMode==='handoffs'){const result=await getPipeline(identifier).catch(()=>null);if(current===generation)pipeline.value=result}
    }else detail.value=null
  }catch(cause){if(current===generation)error.value=cause instanceof Error?cause.message:'任务中心读取失败'}
  finally{inFlight--;if(current===generation)loading.value=false}
}
function chooseTask(task:WorkflowTask){void router.replace({query:{...route.query,task_id:task.id}})}
async function submitReport(){
  if(working.value)return
  working.value=true;error.value='';notice.value=''
  try{
    const sections:ReportSection[]=[]
    let paperIds:string[]|undefined
    if(reportMode.value!=='a'){
      const b=await getBReportInput()
      if(!b.paper_ids.length)throw new Error('B 当前有效知识为空，不能与 A 的全部论文混成同一范围；请等待有效批次自动交接完成，或改为仅生成 A 报告。')
      sections.push(b);paperIds=b.paper_ids
      if(reportMode.value==='abc'){
        try{sections.push(await getCReportInput(b.revision))}
        catch(cause){notice.value=`C 对应知识版本尚未准备好，本次先生成 A+B 报告：${cause instanceof Error?cause.message:'C 统计不可用'}`}
      }
    }
    if(!pendingRequestKey)pendingRequestKey=makeKey('report')
    const task=await createReport({request_key:pendingRequestKey,title:title.value.trim()||'论文数据报告',
      scope:paperIds?{paper_ids:paperIds}:{},sections})
    pendingRequestKey=''
    if(!notice.value)notice.value=`报告任务已创建，已固定 ${sections.map(item=>item.provider).join('+')||'A'} 数据范围。`
    await router.replace({query:{task_id:task.id}});await load(false)
  }catch(cause){error.value=cause instanceof Error?cause.message:'报告创建失败'}finally{working.value=false}
}
async function retry(){
  if(!detail.value||working.value)return
  working.value=true;error.value=''
  try{detail.value=await retryTask(mode.value,detail.value.id);notice.value='失败任务已按原冻结输入重新排队。';await load(false)}
  catch(cause){error.value=cause instanceof Error?cause.message:'任务重试失败'}finally{working.value=false}
}

watch(mode,()=>{sync.value=null;pipeline.value=null;void load()})
watch(selectedTaskId,()=>void load(false))
onMounted(()=>{void load();timer=setInterval(()=>{if(inFlight===0&&(mode.value==='handoffs'||active.value))void load(false)},2000)})
onUnmounted(()=>{generation++;if(timer)clearInterval(timer)})
</script>

<template>
  <section class="standard-page workflow-page">
    <header class="page-heading"><div><div class="eyebrow">A → B → C WORKFLOW</div>
      <h1>{{mode==='handoffs'?'自动交接与版本状态':'报告生成与下载'}}</h1>
      <p>{{mode==='handoffs'?'批次导入成功后自动交给 B；查看接收、知识处理、发布及批次对账结果。':'创建冻结报告任务，组合 A 数据、B 知识证据标签与同版本 C 统计。'}}</p></div>
      <div class="top-actions"><RouterLink class="button button-secondary" :to="mode==='handoffs'?'/admin/reports':'/admin/handoffs'">{{mode==='handoffs'?'进入报告中心':'进入交接中心'}}</RouterLink><button class="button button-secondary" :disabled="loading" @click="load()">刷新</button></div>
    </header>
    <p v-if="notice" class="inline-success" role="status">{{notice}}</p><p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <StatePanel v-if="loading&&!tasks.length" kind="loading" title="正在读取任务与版本"/>
    <template v-else>
      <section v-if="mode==='handoffs'" class="panel create-card">
        <div><h2>自动交接与对账</h2><p>正式批次和补充库批次入库成功后自动交接。失败自动重试，启动时补扫遗漏；已交接批次的撤回会同步通知 B。</p></div>
        <div v-if="sync" class="version-box"><span>对账状态：{{syncLabel(sync.status)}}</span><span>最近核对 {{date(sync.checked_at)}}</span><span>已匹配 {{summaryCount('matched')}} 批</span><span>待补交 {{summaryCount('repair_queued')}} 批</span></div>
        <p v-if="sync?.error" role="status">{{sync.error}}</p>
        <p v-for="issue in syncIssues" :key="issue.batch_code+issue.reason" role="status">{{issue.batch_code}} · {{issue.reason}}</p>
      </section>
      <section v-else class="panel create-card report-create">
        <div><h2>创建冻结报告</h2><p>任务创建时固定论文和知识版本；之后导入、反馈或撤回不会改写已经生成的报告。</p></div>
        <label>报告标题<input v-model="title" class="form-input" maxlength="200"/></label>
        <fieldset><legend>报告内容</legend>
          <label><input v-model="reportMode" type="radio" value="abc"/> A+B，并尝试纳入同版本 C 统计（推荐）</label>
          <label><input v-model="reportMode" type="radio" value="ab"/> A+B：论文、知识、证据、作者标签和质量摘要</label>
          <label><input v-model="reportMode" type="radio" value="a"/> 仅 A：当前有效论文、来源和数据质量</label>
        </fieldset>
        <p class="scope-note">选择 B 时，报告论文范围自动固定为 B 当前 effective 中的论文，避免把 A 全库与 B 局部知识混为同一范围。C 尚未发布对应版本时会明确降级为 A+B。</p>
        <button class="button button-primary" :disabled="working||!title.trim()" @click="submitReport">{{working?'正在固定版本…':'创建报告任务'}}</button>
      </section>

      <div class="workflow-grid">
        <section class="panel task-list"><header><h2>{{mode==='reports'?'报告任务':'交接与撤回通知任务'}}</h2><span>共 {{total}} 项</span></header>
          <p v-if="!tasks.length" class="empty-note">还没有任务。</p>
          <button v-for="task in tasks" :key="task.id" :class="{selected:task.id===selectedTaskId}" @click="chooseTask(task)">
            <span><strong>{{task.title??(task.batch_id?'批次 #'+task.batch_id:'任务')}}</strong><small>{{date(task.created_at)}} · 尝试 {{task.attempts}} 次</small></span>
            <i :class="task.status">{{taskStatus(task.status)}} · {{task.progress}}%</i>
          </button>
        </section>
        <section class="panel task-detail"><StatePanel v-if="!detail" kind="empty" title="请选择任务查看进度"/>
          <template v-else><header><div><span class="eyebrow">TASK DETAIL</span><h2>{{detail.title??(detail.batch_id?'批次 #'+detail.batch_id:'任务详情')}}</h2></div><span class="task-badge" :class="detail.status">{{taskStatus(detail.status)}}</span></header>
            <div class="progress-caption"><strong>{{detail.stage}}</strong><span>{{detail.progress}}%</span></div><div class="progress-track"><i :style="{width:detail.progress+'%'}" :class="detail.status"></i></div>
            <dl><dt>任务 ID</dt><dd><code>{{detail.id}}</code></dd><dt>尝试次数</dt><dd>{{detail.attempts}}</dd><dt>更新时间</dt><dd>{{date(detail.updated_at)}}</dd><template v-if="detail.batch_revision"><dt>批次版本</dt><dd><code>{{short(detail.batch_revision)}}</code></dd></template></dl>
            <p v-if="detail.next_attempt_at" class="scope-note">稍后自动重试 · {{date(detail.next_attempt_at)}}</p><p v-if="detail.error" class="inline-error">{{detail.error}}</p><button v-if="detail.status==='failed'" class="button button-secondary" :disabled="working" @click="retry">按原输入重试</button>

            <section v-if="mode==='handoffs'&&pipeline" class="pipeline"><h3>A/B/C 三阶段状态</h3><article v-for="name in (['A','B','C'] as const)" :key="name"><b>{{name}}</b><div><strong>{{stageStatus(pipeline.stages[name].status)}}</strong><p>{{pipeline.stages[name].message}}</p><small v-if="pipeline.stages[name].revision">知识版本 {{short(pipeline.stages[name].revision)}}</small></div></article></section>
            <section v-if="mode==='reports'&&detail.status==='succeeded'" class="downloads"><h3>报告产物</h3><div class="result-metrics"><span>论文 {{resultNumber(detail,'paper_count')??'—'}} 篇</span><span>ZIP {{resultNumber(detail,'zip_bytes')?.toLocaleString()??'—'}} 字节</span><span>SHA-256 <code>{{short(resultText(detail,'zip_sha256'))}}</code></span></div><div class="download-actions"><a class="button button-primary" :href="reportDownloadUrl(detail.id)" download>下载完整 ZIP</a><a class="button button-secondary" :href="reportFileUrl(detail.id,'report.html')" target="_blank" rel="noopener">打开报告</a><a class="text-button" :href="reportFileUrl(detail.id,'manifest.json')" download>manifest.json</a><a class="text-button" :href="reportFileUrl(detail.id,'checksums.sha256')" download>checksums.sha256</a></div><details><summary>查看全部文件（{{resultFiles(detail).length}}）</summary><a v-for="file in resultFiles(detail)" :key="file.name" :href="reportFileUrl(detail.id,file.name)" download>{{file.name}} · {{file.bytes.toLocaleString()}} B</a></details></section>
            <details v-if="detail.events.length" class="events"><summary>处理事件（{{detail.events.length}}）</summary><article v-for="(event,index) in detail.events" :key="event.at+index"><span>{{date(event.at)}} · {{event.progress}}%</span><p>{{event.message}}</p></article></details>
          </template>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.workflow-page{padding-bottom:32px}.top-actions{display:flex;gap:10px;flex-wrap:wrap}.create-card{padding:22px;margin-bottom:18px;display:grid;grid-template-columns:minmax(230px,1.3fr) minmax(230px,1fr) auto;align-items:end;gap:18px}.create-card h2{font-size:18px;margin-bottom:7px}.create-card p,.empty-note{font-size:12px;color:#6e878f;line-height:1.75}.create-card label{font-size:12px;color:#5c7680}.create-card .form-input{margin-top:7px}.version-box{grid-column:1/-1;display:flex;gap:18px;flex-wrap:wrap;padding:12px 14px;background:#f0f7f5;color:#52746f;font-size:12px;border-radius:7px}.report-create{grid-template-columns:minmax(230px,1.2fr) minmax(270px,1fr) auto}.report-create fieldset{border:0;padding:0;display:grid;gap:7px}.report-create legend{font-size:12px;margin-bottom:7px}.report-create fieldset label{display:flex;gap:7px;align-items:flex-start}.scope-note{grid-column:1/-1}.workflow-grid{display:grid;grid-template-columns:minmax(280px,.72fr) minmax(420px,1.28fr);gap:18px}.task-list>header{display:flex;justify-content:space-between;padding:18px 20px;border-bottom:1px solid #e6efed}.task-list h2,.task-detail h2{font-size:16px}.task-list header span{font-size:11px;color:#789097}.task-list>button{width:100%;border:0;border-bottom:1px solid #edf2f1;background:white;padding:14px 18px;display:flex;justify-content:space-between;align-items:center;gap:12px;text-align:left}.task-list>button:hover,.task-list>button.selected{background:#eff8f5}.task-list button span{display:grid;gap:5px}.task-list button strong{font-size:12px}.task-list button small{font-size:10px;color:#84979e}.task-list button i,.task-badge{font-style:normal;font-size:10px;padding:5px 8px;border-radius:999px;background:#eef3f5;color:#66818a;white-space:nowrap}.task-list .succeeded,.task-badge.succeeded{background:#e6f5ef;color:#26816c}.task-list .failed,.task-badge.failed{background:#fff0e9;color:#ad684c}.task-detail{padding:22px}.task-detail>header{display:flex;justify-content:space-between;gap:14px;align-items:flex-start}.progress-caption{display:flex;justify-content:space-between;margin:22px 0 8px;font-size:12px}.progress-track{height:9px;background:#e9f0ef;border-radius:8px;overflow:hidden}.progress-track i{display:block;height:100%;background:#398f7f}.progress-track i.failed{background:#bc7658}.task-detail dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:9px 14px;font-size:11px;margin:20px 0}.task-detail dt{color:#84969c}.task-detail dd{margin:0;overflow-wrap:anywhere}.pipeline,.downloads,.events{border-top:1px solid #e5edeb;margin-top:20px;padding-top:18px}.pipeline h3,.downloads h3{font-size:14px;margin-bottom:12px}.pipeline article{display:grid;grid-template-columns:34px 1fr;gap:12px;padding:11px 0;border-bottom:1px solid #eef3f2}.pipeline article>b{width:30px;height:30px;display:grid;place-items:center;background:#e8f3f0;color:#2f7e70;border-radius:50%}.pipeline article strong{font-size:12px}.pipeline article p,.pipeline article small{font-size:11px;color:#738a91;line-height:1.6}.result-metrics,.download-actions{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.result-metrics{font-size:11px;color:#667f87;margin-bottom:14px}.downloads details,.events{font-size:11px}.downloads details{margin-top:15px}.downloads details a{display:block;padding:7px 0;color:#2e8476}.events summary,.downloads summary{cursor:pointer}.events article{padding:10px 0;border-bottom:1px solid #edf2f1}.events span{font-size:10px;color:#8b9ca2}.events p{font-size:11px;margin-top:5px}.empty-note{padding:18px 20px}
@media(max-width:950px){.create-card,.report-create{grid-template-columns:1fr}.scope-note,.version-box{grid-column:1}.workflow-grid{grid-template-columns:1fr}}@media(max-width:600px){.workflow-page>.page-heading{flex-direction:column}.task-detail{padding:17px}.create-card{padding:17px}.task-list>button{align-items:flex-start;flex-direction:column}}
</style>
