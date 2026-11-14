<script setup lang="ts">
import {onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {getReadingPapers} from '../services/knowledge-feedback.ts'
import KnowledgeEvidence from '../components/KnowledgeEvidence.vue'
const papers=ref<Array<{paper_id:string;title:string;year:number;venue:string}>>([]),selected=ref(''),error=ref(''),loading=ref(true)
const route=useRoute(),router=useRouter()
const controller=new AbortController()
function selectFromRoute(){const requested=String(route.query.paper_id??'');if(papers.value.some(p=>p.paper_id===requested))selected.value=requested}
onMounted(async()=>{try{papers.value=await getReadingPapers(controller.signal);selectFromRoute();if(!selected.value)selected.value=papers.value[0]?.paper_id??''}catch(e){if(!controller.signal.aborted)error.value=e instanceof Error?e.message:'论文读取失败'}finally{loading.value=false}})
watch(()=>route.query.paper_id,selectFromRoute)
watch(selected,value=>{if(value&&value!==route.query.paper_id)void router.replace({path:route.path,query:{...route.query,paper_id:value}})})
onBeforeUnmount(()=>controller.abort())
</script>
<template><section class="standard-page"><div class="page-heading"><div><div class="eyebrow">B · PUBLIC KNOWLEDGE</div><h1>知识与证据</h1><p>查看 B 当前公共知识、原文依据和单篇关联图；可调整个人视图或提交公共反馈。</p></div><RouterLink v-if="route.query.from==='research'" :to="{path:'/research/papers',query:{batch_id:route.query.batch_id,seed:route.query.seed,q:route.query.q,topic:route.query.topic,method:route.query.method,year:route.query.year}}" class="button button-secondary">返回公共知识图谱</RouterLink></div><p class="knowledge-boundary">管理员处理反馈会更新 B 的公共知识。个人调整仅保存于当前浏览器；C 自动同步尚待接入，因此此页内容不等同于 C 的当前图谱。</p><p v-if="loading" role="status">正在读取论文…</p><p v-if="error" class="inline-error" role="alert">{{error}}</p><section v-if="papers.length" class="panel reading-panel"><label>选择论文<select v-model="selected" class="form-input"><option v-for="paper in papers" :key="paper.paper_id" :value="paper.paper_id">{{paper.year}} · {{paper.venue}} · {{paper.title}}</option></select></label><KnowledgeEvidence v-if="selected" :paper-id="selected"/></section><p v-else-if="!loading&&!error">当前没有可阅读的论文。</p></section></template>
<style scoped>.reading-panel{padding:24px;min-width:0}.reading-panel>label{display:block;font-size:13px}.reading-panel>label select{margin-top:10px}.knowledge-boundary{padding:12px 14px;background:#f3f8f6;border:1px solid #d8e9e2;border-radius:8px;color:#55766d;font-size:12px;line-height:1.8;margin:0 0 18px}</style>
