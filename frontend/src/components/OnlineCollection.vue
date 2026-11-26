<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {RouterLink} from 'vue-router'
import {collectOnline,getOnlineCollection,type OnlineCollection} from '../services/online-collection.ts'
import {retryJob} from '../services/admin.ts'

const emit=defineEmits<{changed:[]}>()
const scope=ref('CVPR:2025'),count=ref(20),keyword=ref(''),working=ref(false),error=ref('')
const current=ref<OnlineCollection|null>(null)
const active=computed(()=>working.value||['queued','running'].includes(current.value?.status??''))
const label=computed(()=>{
 const value=current.value
 if(!value)return ''
 if(value.status==='queued')return '等待采集'
 if(value.status==='running')return value.stage==='collect'?'正在从 OpenAlex 获取论文':'正在入库'
 if(value.status==='failed'||value.status==='partial')return value.next_retry_at?'稍后自动重试':'任务需要重试'
 if(value.stage==='unchanged')return '本次没有新的符合条件的论文'
 if(value.background_task?.status==='succeeded')return '已入库，后台已接收'
 if(value.background_task?.status==='failed')return value.background_task.next_attempt_at?'已入库，后台稍后自动重试':'已入库，后台处理需核对'
 return '已入库，后台知识处理中'
})
let timer:ReturnType<typeof setTimeout>|undefined,disposed=false,generation=0,requestKey=''
watch([scope,count,keyword],()=>{requestKey=''})
function remember(id:number){try{localStorage.setItem('a-last-online-collection',String(id))}catch{}}
function schedule(){
 clearTimeout(timer)
 const item=current.value
 if(!disposed&&item&&(item.status==='queued'||item.status==='running'||item.next_retry_at||
    ['queued','running'].includes(item.background_task?.status??'')||item.background_task?.next_attempt_at))
  timer=setTimeout(()=>void load(item.id),2000)
}
async function load(id:number){
 const version=generation
 try{
  const previous=current.value?.status,value=await getOnlineCollection(id)
  if(disposed||version!==generation)return
  current.value=value;error.value=''
  if(['queued','running','partial'].includes(previous??'')&&value.status==='succeeded')emit('changed')
 }catch(e){if(!disposed&&version===generation)error.value=e instanceof Error?e.message:'采集进度读取失败'}
 finally{schedule()}
}
async function start(){
 if(active.value)return
 clearTimeout(timer);generation++
 working.value=true;error.value=''
 try{
  if(!requestKey)requestKey=crypto.randomUUID()
  const [venue,year]=scope.value.split(':')
  const value=await collectOnline({request_key:requestKey,venue:venue!,year:Number(year),count:count.value,keyword:keyword.value.trim()})
  if(disposed)return
  current.value=value;remember(value.id);requestKey='';schedule()
 }catch(e){if(!disposed)error.value=e instanceof Error?e.message:'采集提交失败'}
 finally{working.value=false}
}
async function retry(){
 if(!current.value||working.value)return
 working.value=true;error.value=''
 try{await retryJob(current.value.id);await load(current.value.id)}
 catch(e){error.value=e instanceof Error?e.message:'重试失败'}finally{working.value=false}
}
onMounted(()=>{try{const id=Number(localStorage.getItem('a-last-online-collection'));if(Number.isInteger(id)&&id>0)void load(id)}catch{}})
onUnmounted(()=>{disposed=true;generation++;clearTimeout(timer)})
</script>

<template>
 <section class="panel online-card" aria-label="在线采集论文">
  <header><div><h2>在线采集论文</h2><p>从 OpenAlex 获取少量新论文，自动去重入库并由后台处理。</p></div></header>
  <form @submit.prevent="start">
   <fieldset :disabled="active">
    <label>会议与年份<select v-model="scope" class="form-input" aria-label="在线采集会议年份"><option value="CVPR:2025">CVPR 2025</option><option value="ICCV:2025">ICCV 2025</option><option value="CVPR:2023">CVPR 2023</option><option value="CVPR:2024">CVPR 2024</option><option value="ICCV:2023">ICCV 2023</option></select></label>
    <label>本次数量<select v-model.number="count" class="form-input" aria-label="在线采集数量"><option v-for="n in [10,20,30,50]" :key="n" :value="n">{{n}} 篇</option></select></label>
    <label>关键词（可选）<input v-model="keyword" class="form-input" maxlength="200" aria-label="在线采集关键词" placeholder="例如 3D、segmentation"/></label>
   </fieldset>
   <button class="button button-primary" :disabled="active" type="submit">{{active?'正在采集与入库…':'采集并入库'}}</button>
  </form>
  <p v-if="error" role="alert">{{error}} <button v-if="current" class="text-button" @click="load(current.id)">重新读取进度</button></p>
  <section v-if="current" class="online-progress" aria-live="polite">
   <div class="online-state"><strong>{{current.display_code}} · {{label}}</strong><span>{{current.progress}}%</span></div>
   <progress :value="current.progress" max="100" aria-label="在线采集进度"/>
   <p>{{current.venue}} {{current.year}} · 本次目标 {{current.requested_count}} 篇 · 已获取 {{current.selected_count}} 篇 · 已入库 {{current.imported_count}} 篇</p>
   <p v-if="current.existing_count">已跳过当前库中 {{current.existing_count}} 篇已有论文。</p>
   <p v-if="current.status==='succeeded'&&current.selected_count<current.requested_count">本轮按查询范围和数量限制，实际获取 {{current.selected_count}} 篇新论文。</p>
   <p v-if="current.error" role="alert">{{current.error}}</p>
   <div class="online-actions"><button v-if="['failed','partial'].includes(current.status)" class="button button-secondary" :disabled="working" @click="retry">重试本次采集</button><RouterLink v-if="current.imported_count" class="text-button" :to="{path:'/admin/jobs',query:{job_id:String(current.id),from:'imports'}}">查看本批论文 →</RouterLink></div>
  </section>
 </section>
</template>

<style scoped>
.online-card{padding:24px;border-color:#beded5;background:linear-gradient(145deg,#fff,#f7fcfa)}.online-card header{margin-bottom:18px}.online-card h2{font-size:18px;color:#365965}.online-card p{font-size:12px;line-height:1.8;color:#718b94;margin-top:10px}.online-card fieldset{padding:0;border:0;display:grid;grid-template-columns:1fr .6fr 1.3fr;gap:16px}.online-card label{font-size:12px;color:#69858b}.online-card .form-input{display:block;width:100%;margin-top:8px}.online-card form>.button{margin-top:18px}.online-progress{border-top:1px solid #dcebe5;margin-top:20px;padding-top:18px}.online-state,.online-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px}.online-progress progress{width:100%;height:12px;margin-top:12px;accent-color:#298675}.online-actions{justify-content:flex-start;margin-top:14px}@media(max-width:650px){.online-card{padding:18px 15px}.online-card fieldset{grid-template-columns:1fr}.online-state{align-items:flex-start}}
</style>
