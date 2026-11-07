<script setup lang="ts">
import {nextTick,onBeforeUnmount,ref,watch} from 'vue'
import {feedbackOwner,readReceipts,saveReceipt} from '../services/feedback-receipts.ts'
import type {FeedbackReceipt} from '../services/feedback-receipts.ts'
import {getFeedbackStatus,withdrawFeedback} from '../services/knowledge-feedback.ts'
const props=defineProps<{paperId:string;refreshVersion:number}>()
const records=ref<FeedbackReceipt[]>([]),error=ref(''),notice=ref(''),busy=ref(false),panel=ref<HTMLElement|null>(null)
const labels={open:'待处理，可撤回',resolved:'已处理',dismissed:'已说明保留',withdrawn:'已撤回'}
let generation=0
async function load(){
  const current=++generation,paperId=props.paperId;busy.value=true;error.value=''
  try{
    records.value=readReceipts(window.localStorage,paperId)
    const statuses=await Promise.all(records.value.map(async item=>({...item,status:(await getFeedbackStatus(item.id)).status})))
    if(current!==generation)return
    records.value=statuses
    for(const item of statuses)saveReceipt(window.localStorage,paperId,item)
  }catch{if(current===generation)error.value='反馈状态暂时无法刷新；本地记录保留，请稍后重试。'}
  finally{if(current===generation)busy.value=false}
}
async function withdraw(item:FeedbackReceipt){
  if(busy.value)return
  const paperId=props.paperId,current=generation;busy.value=true;error.value='';notice.value=''
  try{
    const result=await withdrawFeedback(item.id,feedbackOwner(window.localStorage))
    item.status=result.status;saveReceipt(window.localStorage,paperId,item)
    if(current!==generation)return
    notice.value='反馈已撤回，后台不再将它列为待处理；你的个人调整保持原样。'
  }catch(e){if(current===generation)error.value=e instanceof Error?e.message:'撤回失败，请刷新状态后重试。'}
  finally{if(current===generation)busy.value=false}
}
watch([()=>props.paperId,()=>props.refreshVersion],async()=>{
  await load()
  if(props.refreshVersion){await nextTick();panel.value?.scrollIntoView({block:'nearest'})}
},{immediate:true})
onBeforeUnmount(()=>{generation++})
</script>
<template>
  <section v-if="records.length||error" ref="panel" class="my-feedback" aria-label="我的反馈">
    <header><h4>我的反馈（{{records.length}}）</h4><button type="button" :disabled="busy" @click="load">刷新状态</button></header>
    <p>这里只显示当前浏览器为本篇论文保存的反馈。待处理时可撤回，已处理的结果不能直接撤销。</p>
    <p v-if="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
    <article v-for="item in records" :key="item.id">
      <strong>{{labels[item.status]}}</strong><p>{{item.message}}</p>
      <small>编号：{{item.id}}</small>
      <button v-if="item.status==='open'" type="button" :disabled="busy" @click="withdraw(item)">撤回此反馈</button>
    </article>
  </section>
</template>
<style scoped>
.my-feedback{margin-top:20px;padding-top:16px;border-top:1px solid #d2e2d9;font-size:14px;scroll-margin-top:150px}
header{display:flex;justify-content:space-between;gap:12px;align-items:center}h4{margin:0;font-size:17px}p{line-height:1.8;margin:10px 0;overflow-wrap:anywhere}article{padding:14px 0;border-top:1px solid #e1eae5}small{display:block;overflow-wrap:anywhere;color:#5f7a71}button{min-height:42px;border:1px solid #a9c6b8;border-radius:8px;background:white;padding:9px 14px;color:#365f4c;font:inherit;cursor:pointer}article button{margin-top:12px}button:disabled{opacity:.5;cursor:default}
</style>
