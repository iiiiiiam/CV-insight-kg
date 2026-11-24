<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import StatePanel from './StatePanel.vue'
import {evidenceExcerpt,getConfirmedKnowledge} from '../services/knowledge.ts'
import type {ConfirmedKnowledge as ConfirmedPayload,Evidence,ReviewItem} from '../services/knowledge.ts'
import {safeSourceUrl} from '../services/research.ts'
const props=defineProps<{paperId:string}>()
const data=ref<ConfirmedPayload|null>(null),loading=ref(false),error=ref('')
let generation=0,controller:AbortController|undefined
const items=computed(()=>data.value?[...data.value.entities,...data.value.relations].filter(item=>item.status==='confirmed'):[])
const kinds:Record<string,string>={paper:'论文',author:'作者',institution:'机构',topic:'主题',method:'方法',task:'任务',dataset:'数据集',venue:'会议/期刊'}
const relations:Record<string,string>={has_author:'作者',affiliated_with:'论文上下文中的机构关联',published_in:'发表于',mentions_topic:'提及主题',mentions_method:'提及方法',mentions_task:'提及任务',mentions_dataset:'提及数据集'}
function label(item:ReviewItem){
  if('key' in item.content)return `${kinds[item.content.kind]??item.content.kind} · ${item.content.name}`
  const relation=item.content
  const names=new Map(data.value?.entities.map(e=>{const c=e.content;return 'key' in c?[c.key,c.name]:['','']}))
  return `${names.get(relation.source)??relation.source} —${relations[relation.kind]??relation.kind}→ ${names.get(relation.target)??relation.target}`
}
function excerpt(proof:Evidence){
  if(proof.field==='metadata'||!data.value?.source)return null
  return evidenceExcerpt(data.value.source[proof.field]??'',proof)
}
async function load(){
  const current=++generation;controller?.abort();controller=new AbortController()
  data.value=null;error.value='';loading.value=true
  try{const result=await getConfirmedKnowledge(props.paperId,controller.signal);if(current===generation)data.value=result}
  catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'已确认知识读取失败'}
  finally{if(current===generation)loading.value=false}
}
watch(()=>props.paperId,()=>void load(),{immediate:true})
onBeforeUnmount(()=>{generation++;controller?.abort()})
</script>
<template><section class="confirmed-knowledge" aria-label="B 已确认的实体关系与证据"><div class="confirmed-heading"><h3>B 已确认内容</h3><button class="text-button" :disabled="loading" @click="load">刷新已确认内容</button></div>
  <StatePanel v-if="loading" kind="loading" title="正在读取已确认内容"/>
  <StatePanel v-else-if="error" kind="error" title="已确认内容暂不可用" :description="error" retry @retry="load"/>
  <template v-else-if="data"><p class="small-note">{{data.notice}}</p><p v-if="data.supported" class="small-note">已确认实体 {{data.entities.length}} · 已确认关系 {{data.relations.length}}；证据来自 B 固定样本。</p>
    <p v-if="data.supported&&!items.length" class="empty-confirmed">该论文尚无已确认内容；待审核和已驳回记录不会显示在这里。</p>
    <article v-for="item in items" :key="item.candidate_id" class="confirmed-item"><strong>{{label(item)}}</strong><span class="badge badge-teal">已确认</span><details><summary>查看来源证据（{{item.evidence.length}}）</summary><div v-for="(proof,index) in item.evidence" :key="index" class="confirmed-proof"><p class="small-note">{{proof.field}} · {{proof.field==='metadata'?JSON.stringify(proof.path):`字符 [${proof.start}, ${proof.end})`}}</p><blockquote>{{proof.quote}}</blockquote><details v-if="excerpt(proof)"><summary>原文高亮</summary><p class="original-context">{{excerpt(proof)!.before}}<mark>{{excerpt(proof)!.quote}}</mark>{{excerpt(proof)!.after}}</p></details><a v-if="safeSourceUrl(proof.source_url)" class="text-button" :href="safeSourceUrl(proof.source_url)??undefined" target="_blank" rel="noopener noreferrer">查看证据来源</a></div></details></article>
  </template>
</section></template>
<style scoped>.confirmed-knowledge{margin:28px 0}.confirmed-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:14px}.confirmed-heading h3{margin:0}.confirmed-item{border:1px solid #dce9e5;border-radius:8px;padding:14px;margin-top:12px}.confirmed-item>strong{display:block;line-height:1.7;overflow-wrap:anywhere;color:#3a6e65;font-size:13px;margin-bottom:8px}.confirmed-item>details{margin-top:12px;font-size:12px}.confirmed-proof{padding:12px 0;border-top:1px solid #edf2ef;overflow-wrap:anywhere}.confirmed-proof blockquote{margin:10px 0;padding:10px;background:#f1f8f5;border-left:2px solid #8bbfae;font-size:12px;white-space:pre-wrap}.original-context{font-size:12px;line-height:1.8;padding-top:10px;white-space:pre-wrap}.confirmed-proof .text-button{margin-top:12px}.empty-confirmed{font-size:12px;line-height:1.8;padding:14px;background:#f6f9fa;border-radius:6px;color:#718995}</style>
