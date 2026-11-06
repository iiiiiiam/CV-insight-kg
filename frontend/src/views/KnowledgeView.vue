<script setup lang="ts">
import {onBeforeUnmount,onMounted,ref} from 'vue'
import {useRoute} from 'vue-router'
import {getReadingPapers} from '../services/knowledge-feedback.ts'
import KnowledgeEvidence from '../components/KnowledgeEvidence.vue'
const papers=ref<Array<{paper_id:string;title:string;year:number;venue:string}>>([]),selected=ref(''),error=ref(''),loading=ref(true)
const route=useRoute()
const controller=new AbortController()
onMounted(async()=>{try{papers.value=await getReadingPapers(controller.signal);const requested=String(route.query.paper_id??'');selected.value=papers.value.some(p=>p.paper_id===requested)?requested:papers.value[0]?.paper_id??''}catch(e){if(!controller.signal.aborted)error.value=e instanceof Error?e.message:'论文读取失败'}finally{loading.value=false}})
onBeforeUnmount(()=>controller.abort())
</script>
<template><section class="standard-page"><div class="page-heading"><div><h1>知识与证据</h1><p>查看论文涉及的内容，点击条目回看依据；如有错误或遗漏，可反馈。</p></div></div><p v-if="loading" role="status">正在读取论文…</p><p v-if="error" class="inline-error" role="alert">{{error}}</p><section v-if="papers.length" class="panel reading-panel"><label>选择论文<select v-model="selected" class="form-input"><option v-for="paper in papers" :key="paper.paper_id" :value="paper.paper_id">{{paper.year}} · {{paper.venue}} · {{paper.title}}</option></select></label><KnowledgeEvidence v-if="selected" :paper-id="selected"/></section><p v-else-if="!loading&&!error">当前没有可阅读的论文。</p></section></template>
<style scoped>.reading-panel{padding:24px;min-width:0}.reading-panel>label{display:block;font-size:13px}.reading-panel>label select{margin-top:10px}</style>
