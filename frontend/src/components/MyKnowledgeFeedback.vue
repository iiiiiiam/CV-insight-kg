<script setup lang="ts">
import {nextTick,onBeforeUnmount,ref,watch} from 'vue'
import {feedbackOwner,readReceipts,saveReceipt,feedbackDisplayStatus,refreshReceipts} from '../services/feedback-receipts.ts'
import type {FeedbackReceipt} from '../services/feedback-receipts.ts'
import {getFeedbackStatus,withdrawFeedback,exchangeCloudFeedback} from '../services/knowledge-feedback.ts'
import {auth} from '../stores/auth.ts'
const props=defineProps<{paperId:string;refreshVersion:number}>()
const records=ref<Array<FeedbackReceipt&{refresh_error?:string;archived?:boolean}>>([]),error=ref(''),notice=ref(''),busy=ref(false),panel=ref<HTMLElement|null>(null)
const labels={open:'待处理',resolved:'已处理',dismissed:'已说明保留',withdrawn:'已撤回'}
let generation=0
async function load(){
  const current=++generation,paperId=props.paperId;busy.value=true;error.value=''
  try{
    records.value=readReceipts(window.localStorage,paperId)
    const owner=feedbackOwner(window.localStorage,auth.session?.feedback_token)
    const statuses=await refreshReceipts(records.value,id=>getFeedbackStatus(id,owner))
    if(current!==generation)return
    records.value=statuses
    for(const item of statuses)saveReceipt(window.localStorage,paperId,item)
    const failed=statuses.filter(item=>item.refresh_error).length
    if(failed)error.value=`${failed} 条反馈状态未能更新，已有记录与回复仍保留；请查看对应记录的提示。`
  }catch(e){if(current===generation)error.value=e instanceof Error?e.message:'本地反馈记录暂时无法读取，请稍后重试。'}
  finally{if(current===generation)busy.value=false}
}
async function cloudAction(item:FeedbackReceipt,operation:'send'|'refresh'){
  if(busy.value)return
  const current=generation,paperId=props.paperId;busy.value=true;error.value='';notice.value=''
  try{
    const result=await exchangeCloudFeedback(item.id,feedbackOwner(window.localStorage,auth.session?.feedback_token),operation)
    saveReceipt(window.localStorage,paperId,{...item,cloud:result})
    if(current!==generation)return
    item.cloud=result;notice.value=operation==='send'?'团队已收到反馈。':'已查询团队处理结果。'
  }catch(e){if(current===generation)error.value=e instanceof Error?e.message:'云端操作未完成，本地反馈保留。'}
  finally{if(current===generation)busy.value=false}
}
async function withdraw(item:FeedbackReceipt){
  if(busy.value)return
  const paperId=props.paperId,current=generation;busy.value=true;error.value='';notice.value=''
  try{
    const result=await withdrawFeedback(item.id,feedbackOwner(window.localStorage,auth.session?.feedback_token))
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
    <p>本篇论文的反馈与回复保存在这里，点击“刷新回复”查看团队最新处理结果。</p>
    <p v-if="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
    <article v-for="item in records" :key="item.id">
      <div class="feedback-heading"><strong>{{labels[feedbackDisplayStatus(item)]}}</strong><small v-if="item.cloud">{{item.cloud.delivery==='sent'?'已送达团队':'待发送'}}</small></div>
      <p class="feedback-message">{{item.message}}</p><p v-if="item.archived" class="archive-note">当前连接的软件数据中暂时无法关联这条历史反馈，可能使用了不同的数据目录或安装环境。这里保留浏览器保存的内容与上次回复，不代表团队删除了反馈。</p><p v-if="item.refresh_error" class="inline-error" role="alert">状态未更新：{{item.refresh_error}}</p>
      <div class="reply-content"><strong>团队回复</strong><p>{{item.cloud?.feedback?.processing_note||(feedbackDisplayStatus(item)==='open'?'暂无回复':'暂无文字回复')}}</p></div>
      <div v-if="item.cloud&&!item.archived" class="cloud-reply">
        <button v-if="item.status!=='withdrawn'&&item.cloud.delivery!=='sent'" type="button" :disabled="busy" @click="cloudAction(item,'send')">发送给团队 / 重试</button>
        <button v-if="item.cloud.delivery==='sent'" type="button" :disabled="busy" @click="cloudAction(item,'refresh')">刷新回复</button>
      </div>
      <button v-if="!item.archived&&item.status==='open'&&item.cloud?.delivery!=='sent'" type="button" :disabled="busy" @click="withdraw(item)">撤回此反馈</button>
      <details class="receipt-details"><summary>记录信息</summary><small>反馈编号：{{item.id}}</small><small v-if="item.cloud?.feedback">团队回执：{{item.cloud.feedback.id}}</small>
        <template v-if="!item.archived&&item.cloud?.delivery==='sent'&&item.status==='open'&&feedbackDisplayStatus(item)==='open'"><p>此操作只撤回本机记录，已送达团队的反馈仍会保留。</p><button type="button" :disabled="busy" @click="withdraw(item)">撤回本机记录</button></template>
      </details>
    </article>
  </section>
</template>
<style scoped>
.my-feedback{margin-top:20px;padding-top:16px;border-top:1px solid #d2e2d9;font-size:14px;scroll-margin-top:150px}
.feedback-heading{display:flex;align-items:center;gap:12px}.feedback-heading>strong{color:#365f4c}.reply-content{padding:12px 16px;background:#f3f8f6;border-radius:8px;margin:12px 0}.reply-content p{margin-bottom:0}.receipt-details{margin-top:14px;color:#5f7a71}.receipt-details summary{cursor:pointer;font-size:13px}
header{display:flex;justify-content:space-between;gap:12px;align-items:center}h4{margin:0;font-size:17px}p{line-height:1.8;margin:10px 0;overflow-wrap:anywhere}article{padding:14px 0;border-top:1px solid #e1eae5}small{display:block;overflow-wrap:anywhere;color:#5f7a71}button{min-height:42px;border:1px solid #a9c6b8;border-radius:8px;background:white;padding:9px 14px;color:#365f4c;font:inherit;cursor:pointer}article button{margin-top:12px}button:disabled{opacity:.5;cursor:default}
</style>
