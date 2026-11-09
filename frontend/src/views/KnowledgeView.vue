<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {getReadingPapers} from '../services/knowledge-feedback.ts'
import KnowledgeEvidence from '../components/KnowledgeEvidence.vue'
import {filterPaperTitles,readLastPaper,rememberPaper,resolveReadingPaper} from '../services/knowledge-navigation.ts'
const papers=ref<Array<{paper_id:string;title:string;year:number;venue:string}>>([]),selected=ref(''),error=ref(''),loading=ref(true)
const route=useRoute(),router=useRouter()
const controller=new AbortController()
const search=ref(''),historyNote=ref('')
const matches=computed(()=>filterPaperTitles(papers.value,search.value))
function selectFromRoute(){
  if(!papers.value.length)return
  let remembered:string|null=null
  try{remembered=readLastPaper(window.localStorage)}catch{/* The URL still preserves the current paper when storage is blocked. */}
  selected.value=resolveReadingPaper(papers.value,String(route.query.paper_id??''),remembered)
}
function openFirstMatch(){if(matches.value[0])selected.value=matches.value[0].paper_id}
onMounted(async()=>{try{papers.value=await getReadingPapers(controller.signal);selectFromRoute()}catch(e){if(!controller.signal.aborted)error.value=e instanceof Error?e.message:'论文读取失败'}finally{loading.value=false}})
watch(()=>route.query.paper_id,selectFromRoute)
watch(selected,value=>{
  if(!value)return
  try{historyNote.value=rememberPaper(window.localStorage,value)?'':'浏览器暂时无法记住阅读位置，当前链接仍可用于重新打开本篇论文。'}catch{historyNote.value='浏览器暂时无法记住阅读位置，当前链接仍可用于重新打开本篇论文。'}
  if(value!==route.query.paper_id)void router.replace({path:route.path,query:{...route.query,paper_id:value}})
})
onBeforeUnmount(()=>controller.abort())
</script>
<template>
  <section class="standard-page">
    <div class="page-heading">
      <div><div class="eyebrow">论文阅读</div><h1>知识与证据</h1><p>浏览论文涉及的方法、任务和数据集，点击条目查看依据。</p></div>
      <RouterLink v-if="route.query.from==='research'" :to="{path:'/research/papers',query:{batch_id:route.query.batch_id,seed:route.query.seed,q:route.query.q,topic:route.query.topic,method:route.query.method,year:route.query.year}}" class="button button-secondary">返回公共知识图谱</RouterLink>
    </div>
    <details class="knowledge-boundary"><summary>内容更新说明</summary><p>管理员处理反馈后，刷新本页可查看更新。个人调整只影响当前浏览器；其他检索和图谱页面暂未同步这些修正。</p></details>
    <p v-if="loading" role="status">正在读取论文…</p>
    <p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <section v-if="papers.length" class="panel reading-panel">
      <form class="paper-search" role="search" @submit.prevent="openFirstMatch">
        <label for="knowledge-title-search">按论文标题查找</label>
        <div class="search-controls"><input id="knowledge-title-search" v-model="search" type="search" class="form-input" placeholder="输入标题关键词，如 diffusion、video" aria-describedby="knowledge-search-help"/><button v-if="search" type="button" class="button button-secondary" @click="search=''">清空</button></div>
        <p id="knowledge-search-help">支持多个关键词，空格分隔；点击结果打开论文。</p>
        <template v-if="search.trim()">
          <p role="status">{{matches.length?'找到 '+matches.length+' 篇论文':'没有找到匹配的论文，请换个关键词。'}}</p>
          <div v-if="matches.length" class="search-results" aria-label="标题搜索结果"><button v-for="paper in matches" :key="paper.paper_id" type="button" class="search-result" :class="{active:selected===paper.paper_id}" :aria-pressed="selected===paper.paper_id" @click="selected=paper.paper_id"><strong>{{paper.title}}</strong><span>{{paper.year}} · {{paper.venue}}{{selected===paper.paper_id?' · 当前阅读':''}}</span></button></div>
        </template>
      </form>
      <label>选择论文（共 {{papers.length}} 篇）<select v-model="selected" class="form-input"><option v-for="paper in papers" :key="paper.paper_id" :value="paper.paper_id">{{paper.year}} · {{paper.venue}} · {{paper.title}}</option></select></label>
      <p v-if="historyNote" class="reading-note" role="status">{{historyNote}}</p>
      <KnowledgeEvidence v-if="selected" :paper-id="selected"/>
    </section>
    <p v-else-if="!loading&&!error">当前没有可阅读的论文。</p>
  </section>
</template>
<style scoped>.reading-panel{padding:24px;min-width:0}.reading-panel>label{display:block;font-size:14px}.reading-panel>label select{margin-top:10px}.knowledge-boundary{color:#55766d;font-size:14px;line-height:1.8;margin:0 0 18px}.knowledge-boundary summary{cursor:pointer;padding:8px 0}.knowledge-boundary p{margin:8px 0}.paper-search{margin-bottom:20px}.paper-search label{font-size:15px;display:block;margin-bottom:8px}.search-controls{display:flex;gap:8px}.search-controls input{min-width:0;flex:1}.paper-search p,.reading-note{font-size:14px;line-height:1.7;color:#55766d;margin:8px 0}.search-results{max-height:260px;overflow:auto;display:grid;gap:8px}.search-result{padding:12px;text-align:left;background:white;border:1px solid #d6e4de;border-radius:8px;font:inherit;cursor:pointer;overflow-wrap:anywhere}.search-result strong,.search-result span{display:block}.search-result span{font-size:13px;color:#55766d;margin-top:5px}.search-result.active{background:#edf7f1;border-color:#7ba68e}.search-result:focus-visible{outline:2px solid #497e69;outline-offset:2px}</style>
