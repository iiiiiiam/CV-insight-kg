<script setup lang="ts">
import {computed,onUnmounted,ref,watch} from 'vue'
import {RouterLink} from 'vue-router'
import FormalBatchControls from './FormalBatchControls.vue'
import {getJob,type JobInfo} from '../services/admin.ts'
import {batchCode} from '../services/import-progress.ts'

const props=defineProps<{jobs:JobInfo[];currentJobId?:number;fromImports?:boolean}>()
const emit=defineEmits<{changed:[id:number]}>()
const choices=computed(()=>props.jobs.filter(j=>['reserve','formal'].includes(j.kind)).sort((a,b)=>b.id-a.id))
const available=computed(()=>choices.value.filter(j=>j.batch_state!=='withdrawn'&&!['queued','running'].includes(j.status)))
const selected=ref(0),detail=ref<JobInfo|null>(null),busy=ref(false),withdrawing=ref(false),error=ref('')
let generation=0
const date=(value:string)=>value.slice(0,16).replace('T',' ')
const state=(job:JobInfo)=>job.batch_state==='withdrawn'?'已撤回':['queued','running'].includes(job.status)?'导入中':'可撤回'
const label=(job:JobInfo)=>`${batchCode(job)} · ${job.venue} ${job.year} · ${date(job.created_at)} · ${state(job)}`
async function load(){
 const v=++generation;detail.value=null;error.value=''
 if(!selected.value){busy.value=false;return}
 busy.value=true
 try{const value=await getJob(selected.value);if(v===generation)detail.value=value}
 catch(e){if(v===generation)error.value=e instanceof Error?e.message:'批次详情读取失败'}
 finally{if(v===generation)busy.value=false}
}
watch(()=>props.currentJobId,id=>{if(id&&choices.value.some(j=>j.id===id))selected.value=id},{immediate:true})
watch(choices,list=>{
 if(!selected.value&&props.currentJobId&&list.some(j=>j.id===props.currentJobId))selected.value=props.currentJobId
 else if(selected.value&&!list.some(j=>j.id===selected.value))selected.value=0
},{immediate:true})
watch(()=>{const current=choices.value.find(j=>j.id===selected.value);return `${selected.value}:${current?.status}:${current?.succeeded}:${current?.failed}:${current?.batch_state}`},load,{immediate:true})
onUnmounted(()=>generation++)
</script>

<template>
 <section class="panel withdrawal-panel" aria-labelledby="withdrawal-heading">
  <header><div><h2 id="withdrawal-heading">批次撤回</h2><p>选择需要撤回的导入批次，核对后再确认。</p></div></header>
  <p v-if="!choices.length" class="withdrawal-empty">还没有手动导入批次，导入论文后可在这里选择撤回。</p>
  <template v-else>
   <p v-if="!available.length" class="withdrawal-empty">当前没有可撤回的批次。已撤回和正在导入的批次会标注在列表中。</p>
   <label class="withdrawal-label" for="withdrawal-batch">选择撤回批次</label>
   <select id="withdrawal-batch" v-model.number="selected" class="form-input" :disabled="withdrawing">
    <option :value="0">请选择要撤回的批次</option>
    <option v-for="item in choices" :key="item.id" :value="item.id" :disabled="item.batch_state==='withdrawn'||['queued','running'].includes(item.status)">{{label(item)}}</option>
   </select>
   <p v-if="busy" role="status" class="withdrawal-empty">正在读取所选批次…</p>
   <p v-else-if="error" role="alert" class="withdrawal-error">{{error}} <button class="text-button" @click="load">重试读取</button></p>
   <template v-else-if="detail">
    <div class="withdrawal-summary"><strong>{{batchCode(detail)}}</strong><span>{{detail.venue}} {{detail.year}}</span><span>导入时间 {{date(detail.created_at)}}</span><span>本批论文 {{detail.paper_count??detail.quality?.total??0}} 篇</span><RouterLink v-if="!withdrawing" class="text-button" :to="{path:'/admin/jobs',query:{job_id:String(detail.id),from:fromImports?'imports':undefined}}">查看本批论文 →</RouterLink></div>
    <FormalBatchControls :id="detail.id" :status="detail.status" @pending="withdrawing=$event" @changed="emit('changed',detail.id)"/>
   </template>
  </template>
 </section>
</template>

<style scoped>
.withdrawal-panel{padding:24px;margin-bottom:20px}.withdrawal-panel h2{font-size:18px;color:#365965}.withdrawal-panel header p,.withdrawal-empty{font-size:12px;line-height:1.8;color:#789099;margin-top:8px}.withdrawal-label{display:block;font-size:12px;color:#66818a;margin:18px 0 9px}.withdrawal-panel select{width:100%;max-width:850px;text-overflow:ellipsis}.withdrawal-summary{display:flex;align-items:center;flex-wrap:wrap;gap:12px 20px;margin:18px 0;font-size:12px;color:#68848b}.withdrawal-summary strong{color:#298675}.withdrawal-error{color:#a76f4b;font-size:12px;margin-top:12px}@media(max-width:600px){.withdrawal-panel{padding:18px 15px}.withdrawal-summary{gap:10px 14px}}
</style>
