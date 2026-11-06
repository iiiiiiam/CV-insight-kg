<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {evidenceExcerpt} from '../services/knowledge.ts'
import {safeSourceUrl} from '../services/research.ts'
import {getReading,itemName,KIND_NAMES,sendFeedback} from '../services/knowledge-feedback.ts'
import type {ReadingKnowledge} from '../services/knowledge-feedback.ts'
const props=defineProps<{paperId:string}>()
const view=ref<ReadingKnowledge|null>(null),loading=ref(false),error=ref(''),selectedId=ref(''),proofIndex=ref(0)
const collection=ref<'entities'|'relations'>('entities'),form=ref<'item'|'missing'|null>(null)
const message=ref(''),term=ref(''),saving=ref(false),notice=ref('')
let generation=0,controller:AbortController|undefined
const items=computed(()=>view.value?.[collection.value]??[])
const selected=computed(()=>items.value.find(i=>i.candidate_id===selectedId.value))
const proof=computed(()=>selected.value?.evidence[proofIndex.value])
const excerpt=computed(()=>{
  if(!proof.value||!view.value||proof.value.field==='metadata')return null
  return evidenceExcerpt(view.value.paper[proof.value.field]??'',proof.value)
})
async function load(){
  const current=++generation;controller?.abort();controller=new AbortController()
  loading.value=true;error.value='';view.value=null;form.value=null;selectedId.value=''
  try{const result=await getReading(props.paperId,controller.signal);if(current===generation)view.value=result}
  catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'知识读取失败'}
  finally{if(current===generation)loading.value=false}
}
watch(()=>props.paperId,()=>{notice.value='';void load()},{immediate:true})
watch([collection,view],()=>{selectedId.value=items.value[0]?.candidate_id??'';proofIndex.value=0;form.value=null})
watch(selectedId,()=>{proofIndex.value=0;form.value=null;message.value=''})
function openForm(mode:'item'|'missing'){form.value=mode;message.value='';term.value='';notice.value=''}
async function submit(){
  if(!view.value||saving.value)return
  saving.value=true;error.value=''
  try{
    const result=await sendFeedback({paper_id:props.paperId,revision:view.value.revision,message:message.value,
      ...(form.value==='missing'?{term:term.value}:{candidate_id:selected.value?.candidate_id})})
    notice.value=`${result.duplicate?'该内容已有待处理反馈':'反馈已提交'}，编号 ${result.id}。`;form.value=null
  }catch(e){error.value=e instanceof Error?e.message:'提交失败，请稍后重试'}
  finally{saving.value=false}
}
onBeforeUnmount(()=>{generation++;controller?.abort()})
</script>
<template><section class="knowledge-evidence">
  <header><h3>知识与原文依据</h3><button class="text-button" :disabled="loading||saving" @click="load">刷新内容</button></header>
  <p class="small-note">点击条目查看依据；如有错误或遗漏，可反馈。</p>
  <p v-if="loading" role="status">正在读取知识与证据…</p>
  <p v-if="error" class="inline-error" role="alert">{{error}}</p>
  <p v-if="notice" class="inline-success" role="status">{{notice}}</p>
  <template v-if="view">
    <div class="tools"><button class="button button-secondary" :class="{active:collection==='entities'}" @click="collection='entities'">对象 {{view.entities.length}}</button><button class="button button-secondary" :class="{active:collection==='relations'}" @click="collection='relations'">关联 {{view.relations.length}}</button><button class="text-button" :disabled="saving" @click="openForm('missing')">反馈遗漏名称</button></div>
    <div class="evidence-layout"><div class="item-list"><button v-for="item in items" :key="item.candidate_id" class="knowledge-item" :class="{active:selectedId===item.candidate_id}" :disabled="saving" @click="selectedId=item.candidate_id"><small>{{'name' in item.content?KIND_NAMES[item.content.kind]:'关联'}}</small><strong>{{itemName(item,view)}}</strong></button><p v-if="!items.length">当前没有可展示的条目。</p></div>
      <div class="proof-panel"><template v-if="selected"><h4>{{itemName(selected,view)}}</h4><label>依据<select v-model.number="proofIndex" class="form-input"><option v-for="(p,i) in selected.evidence" :key="i" :value="i">{{i+1}} · {{p.field==='title'?'标题':p.field==='abstract'?'摘要':'来源字段'}}</option></select></label>
        <template v-if="proof"><blockquote>{{proof.quote}}</blockquote><p v-if="excerpt" class="source-text">{{excerpt.before}}<mark>{{excerpt.quote}}</mark>{{excerpt.after}}</p><p v-else-if="proof.field==='metadata'" class="small-note">来源字段：{{proof.path.join(' → ')}}</p><p v-else class="inline-error">这条依据与当前原文不一致，请反馈。</p><a v-if="safeSourceUrl(proof.source_url)" :href="safeSourceUrl(proof.source_url)??undefined" target="_blank" rel="noopener noreferrer" class="text-button">查看来源</a></template>
        <button class="text-button report-button" :disabled="saving" @click="openForm('item')">这条信息有误，反馈问题</button>
      </template><p v-else>选择左侧条目查看原文依据。</p></div></div>
    <form v-if="form" class="feedback-form" @submit.prevent="submit"><h4>{{form==='missing'?'申请识别遗漏名称':'反馈当前信息'}}</h4><p class="small-note">{{form==='missing'?'填写标题或摘要里实际出现的名称，维护人员会核对类别与词条。':'请说明哪里不合适，提交反馈不会立即删除信息。'}}</p><label v-if="form==='missing'">原文名称<input v-model="term" class="form-input" maxlength="200" required :disabled="saving"/></label><label>问题描述<textarea v-model="message" maxlength="2000" required rows="3" :disabled="saving"></textarea></label><div class="tools"><button class="button button-primary" :disabled="saving||!message.trim()||(form==='missing'&&!term.trim())">{{saving?'提交中…':'提交反馈'}}</button><button type="button" class="text-button" :disabled="saving" @click="form=null">取消</button></div></form>
  </template>
</section></template>
<style scoped>
.knowledge-evidence{margin:24px 0;min-width:0}header,.tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap}header{justify-content:space-between}.tools{margin:16px 0}.evidence-layout{display:grid;grid-template-columns:minmax(190px,.8fr) minmax(240px,1.2fr);gap:18px}.item-list{max-height:550px;overflow:auto}.knowledge-item{display:block;width:100%;text-align:left;border:1px solid #dce8e5;background:white;border-radius:7px;padding:12px;margin-bottom:8px;overflow-wrap:anywhere}.knowledge-item strong{display:block;line-height:1.7}.knowledge-item small{color:#6e8791}.active{background:#edf8f3;border-color:#8bbfae}.proof-panel{border:1px solid #dce8e5;border-radius:8px;padding:16px;min-width:0}.proof-panel h4{line-height:1.7;overflow-wrap:anywhere}.proof-panel label,.feedback-form label{display:block;margin:14px 0;font-size:12px}blockquote{margin:14px 0;border-left:3px solid #69a38d;padding:10px;background:#f1f8f4;white-space:pre-wrap;overflow-wrap:anywhere}.source-text{max-height:380px;overflow:auto;font-size:13px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere}mark{background:#ffdf79}.report-button{display:block;margin-top:20px}.feedback-form{margin-top:20px;padding:18px;background:#f6faf8;border:1px solid #dce8e5;border-radius:8px}textarea{display:block;width:100%;margin-top:8px;padding:10px;border:1px solid #cfded9;border-radius:6px;font:inherit}@media(max-width:850px){.evidence-layout{grid-template-columns:1fr}}
</style>
