<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue'
import {RouterLink} from 'vue-router'
import {getSchedules,saveSchedule,runSchedule,retryCollection,type ScheduleData,type CollectionPlan} from '../services/schedules.ts'

const data=ref<ScheduleData|null>(null),busy=ref(false),error=ref(''),readError=ref(''),notice=ref(''),selected=ref('daily-papers')
const form=ref({id:'daily-papers',enabled:false,time:'09:00',timezone:'Asia/Shanghai',
  scopes:['CVPR:2023','ICCV:2021'],
  with_annotations:true,max_attempts:3,retry_seconds:300})
const revision=ref<string|null>(null)
const options=['CVPR:2023','CVPR:2024','CVPR:2025','ICCV:2021','ICCV:2023','ICCV:2025']
const scopes=computed(()=>Array.from(new Set([...options,...form.value.scopes])))
const saved=computed(()=>data.value?.schedules.find(p=>p.id===selected.value))
const runs=computed(()=>data.value?.runs.filter(r=>r.schedule_id===selected.value)??[])
const hasActive=computed(()=>runs.value.some(r=>!['succeeded','unchanged','partial','failed','cancelled'].includes(r.status)))
const label=(value:string)=>({queued:'等待执行',pending:'等待采集',running:'执行中',collecting:'采集中',
  waiting_import:'等待或正在入库',retry_wait:'等待重试',retrying:'重试中',paused:'来源已暂停',
  succeeded:'已完成',unchanged:'无新变化',partial:'部分失败',failed:'失败',cancelled:'已撤回'} as Record<string,string>)[value]??value
const date=(value:string|null)=>value?new Date(value).toLocaleString('zh-CN',{hour12:false,timeZone:saved.value?.timezone??form.value.timezone}):'—'
let timer:ReturnType<typeof setTimeout>|undefined,disposed=false,controller:AbortController|null=null

function hydrate(plan?:CollectionPlan){
  if(!plan)return
  const {id,enabled,time,timezone,scopes,with_annotations,max_attempts,retry_seconds}=plan
  selected.value=id
  form.value={id,enabled,time,timezone,scopes:[...scopes],with_annotations,max_attempts,retry_seconds}
  revision.value=plan.revision
}
async function load(reset=false){
  controller?.abort();const requestController=new AbortController();controller=requestController
  try{
    const value=await getSchedules(requestController.signal)
    if(disposed||requestController.signal.aborted)return
    data.value=value;readError.value=''
    if(reset)hydrate(value.schedules.find(p=>p.id===selected.value)??value.schedules[0])
  }catch(e){if(!disposed&&!requestController.signal.aborted)readError.value=e instanceof Error?e.message:'无法读取定时计划'}
}
async function save(){
  busy.value=true;error.value='';notice.value=''
  try{
    data.value=await saveSchedule(form.value,revision.value)
    if(disposed)return
    hydrate(data.value.schedules.find(p=>p.id===selected.value))
    notice.value=form.value.enabled?'定时计划已启用，将按保存的时间执行。':'定时计划已暂停，已经启动的任务继续处理。'
  }catch(e){if(!disposed)error.value=e instanceof Error?e.message:'定时计划保存失败'}
  finally{if(!disposed)busy.value=false}
}
async function runOnce(){
  busy.value=true;error.value='';notice.value=''
  try{
    const result=await runSchedule(selected.value)
    if(disposed)return
    notice.value=result.replay?`运行 #${result.run_id} 已在处理中。`:`已提交运行 #${result.run_id}，采集后自动去重入库。`
    await load()
  }catch(e){if(!disposed)error.value=e instanceof Error?e.message:'提交执行失败'}
  finally{if(!disposed)busy.value=false}
}
async function retry(id:number){
  busy.value=true;error.value='';notice.value=''
  try{await retryCollection(id);if(disposed)return;notice.value=`运行 #${id} 已提交重试，保留原进度和批次。`;await load()}
  catch(e){if(!disposed)error.value=e instanceof Error?e.message:'重试提交失败'}
  finally{if(!disposed)busy.value=false}
}
async function poll(){await load();if(!disposed)timer=setTimeout(poll,5000)}
onMounted(async()=>{await load(true);if(!disposed)timer=setTimeout(poll,5000)})
onUnmounted(()=>{disposed=true;controller?.abort();if(timer)clearTimeout(timer)})
</script>

<template>
  <section class="panel schedule-panel" aria-label="定时采集与入库">
    <header><div><h2>定时采集与入库</h2><p>按计划从 DBLP 和 OpenAlex 获取论文，只将新增或变化的记录写入数据库。</p></div>
      <span class="runtime" :class="{online:data?.runtime.connected}">{{data?.runtime.connected?'调度服务已连接':'调度服务未连接'}}</span>
    </header>
    <p v-if="error" role="alert" class="schedule-error">{{error}}</p>
    <p v-if="readError" role="alert" class="schedule-error">{{readError}}</p>
    <p v-if="notice" role="status" class="schedule-notice">{{notice}}</p>
    <label v-if="(data?.schedules.length??0)>1" class="plan-selector">计划<select v-model="selected" class="form-input" aria-label="选择定时计划" @change="hydrate(data?.schedules.find(p=>p.id===selected))"><option v-for="plan in data?.schedules" :key="plan.id" :value="plan.id">{{plan.id}}</option></select></label>
    <form @submit.prevent="save">
      <fieldset :disabled="busy">
        <label class="enable"><input v-model="form.enabled" type="checkbox" aria-label="启用每日定时采集"/> 启用每日定时采集</label>
        <div class="schedule-fields">
          <label>每日执行时间<input v-model="form.time" class="form-input" type="time" required aria-label="每日执行时间"/></label>
          <label>时区<select v-model="form.timezone" class="form-input" aria-label="采集时区"><option value="Asia/Shanghai">北京时间</option><option value="UTC">UTC</option><option v-if="!['Asia/Shanghai','UTC'].includes(form.timezone)" :value="form.timezone">{{form.timezone}}</option></select></label>
          <label>每轮最多尝试<input v-model.number="form.max_attempts" class="form-input" type="number" min="1" max="8" required aria-label="采集最多尝试次数"/></label>
          <label>重试间隔（秒）<input v-model.number="form.retry_seconds" class="form-input" type="number" min="1" max="86400" required aria-label="采集重试间隔"/></label>
        </div>
        <div class="scope-options" role="group" aria-label="采集会议年份"><label v-for="scope in scopes" :key="scope"><input v-model="form.scopes" type="checkbox" :value="scope" :aria-label="`采集 ${scope}`"/>{{scope.replace(':',' ')}}</label></div>
        <label><input v-model="form.with_annotations" type="checkbox" aria-label="采集主题和关键词"/> 同时获取 OpenAlex 主题和关键词</label>
      </fieldset>
      <p class="next-run">{{saved?.enabled?`下次执行：${date(saved.next_run_utc)}`:'每日计划未启用。'}} 暂停计划不影响已启动的任务；执行一次使用已保存的范围。</p>
      <div class="schedule-actions"><button class="button button-primary" :disabled="busy||!form.scopes.length">保存定时计划</button><button class="button button-secondary" type="button" :disabled="busy||!saved||!data?.runtime.connected||hasActive" @click="runOnce">执行一次</button><button class="button button-secondary" type="button" :disabled="busy" @click="load(true)">重新读取计划</button><button class="button button-secondary" type="button" :disabled="busy" @click="load()">刷新运行记录</button></div>
    </form>
    <section class="collection-runs" aria-label="最近定时运行">
      <h3>最近运行</h3><p v-if="!runs.length">暂无运行记录。保存计划后可执行一次，或等待下次定时执行。</p>
      <article v-for="run in runs" :key="run.run_id" class="collection-run">
        <div class="run-heading"><strong>运行 #{{run.run_id}} · {{label(run.status)}}</strong><span>{{date(run.scheduled_for_utc)}} · {{run.trigger==='manual'?'手动触发':run.trigger==='catch_up'?'补执行':'定时触发'}}</span><button v-if="['failed','partial'].includes(run.status)" class="button button-secondary" :disabled="busy" @click="retry(run.run_id)">重试运行 #{{run.run_id}}</button></div>
        <div v-for="task in run.tasks" :key="`${task.venue}:${task.year}`" class="collection-task">
          <div><strong>{{task.venue}} {{task.year}}</strong><span>{{label(task.status)}}{{task.batch_state==='withdrawn'?' · 批次已撤回':''}}</span></div>
          <p>读取来源记录 {{task.collected_records}} 条 · 未变化 {{task.unchanged_records}} 条 · 已尝试 {{task.attempts}} 次</p>
          <div v-if="task.progress.total" class="schedule-progress"><progress :value="task.progress.percent" max="100" :aria-label="`${task.venue} ${task.year} 入库进度`"/><span>{{task.progress.finished}} / {{task.progress.total}} 条</span></div>
          <p v-if="task.error" class="schedule-error">{{task.error}}</p>
          <p v-if="task.next_attempt_utc">下次重试：{{date(task.next_attempt_utc)}}</p>
          <RouterLink v-if="task.job_id" :to="{path:'/admin/jobs',query:{job_id:String(task.job_id),from:'sources'}}">查看 {{task.display_code}} 批次 →</RouterLink>
        </div>
      </article>
    </section>
  </section>
</template>

<style scoped>
.schedule-panel{margin-top:24px;padding:24px}.schedule-panel header{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.schedule-panel h2{font-size:18px}.schedule-panel h3{font-size:15px;margin:22px 0 12px}.schedule-panel p{font-size:12px;line-height:1.8;color:#69858b;margin:10px 0}.runtime{font-size:11px;background:#eef2f3;color:#73878b;border-radius:20px;padding:7px 12px;white-space:nowrap}.runtime.online{background:#e5f4ec;color:#39775d}.schedule-panel fieldset{border:0;padding:0;min-width:0}.schedule-panel label{display:block;font-size:12px;margin:12px 0;color:#47656e}.schedule-fields{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.schedule-panel .form-input{display:block;width:100%;margin-top:7px}.scope-options{display:flex;gap:8px 22px;flex-wrap:wrap}.scope-options label{display:flex;gap:7px}.schedule-actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.collection-run{border-top:1px solid #e1ebea;padding:18px 0}.run-heading{display:flex;align-items:center;gap:14px;flex-wrap:wrap;font-size:12px}.run-heading span{color:#69858b}.collection-task{padding:14px;border:1px solid #e1ebea;border-radius:8px;margin-top:12px;font-size:12px;overflow-wrap:anywhere}.collection-task>div:first-child{display:flex;justify-content:space-between;gap:12px}.collection-task a{color:#328b78}.schedule-progress{display:flex;gap:12px;align-items:center}.schedule-progress progress{max-width:240px;width:60%;accent-color:#458f7d}.schedule-panel .schedule-error{color:#af4b3d}.schedule-panel .schedule-notice{color:#39775d}@media(max-width:900px){.schedule-fields{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.schedule-panel{padding:16px}.schedule-panel header{flex-direction:column}.schedule-fields{grid-template-columns:1fr 1fr}.schedule-actions .button{flex:1 1 auto}.collection-task>div:first-child{flex-wrap:wrap}}
</style>
