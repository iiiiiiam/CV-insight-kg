<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import type {CDetail,CNode} from '../types.ts'
import {graphResearch,searchGraphEntities} from '../services/graph.ts'
import CGraphDetail from '../components/CGraphDetail.vue'
import DetailDrawer from '../components/DetailDrawer.vue'
import StatePanel from '../components/StatePanel.vue'
const route=useRoute(),router=useRouter(),query=ref(''),batch=ref(''),items=ref<CNode[]>([]),detail=ref<CDetail|null>(null),error=ref(''),loading=ref(false),truncated=ref(false),drawer=ref<string|null>(null)
const kind=computed(()=>route.path.includes('/authors')?'author':'institution')
let controller:AbortController|undefined,generation=0
async function load(){
  const current=++generation;controller?.abort();controller=new AbortController();loading.value=true;error.value='';detail.value=null;drawer.value=null
  try{
    if(route.params.id){const value=await graphResearch.getDetail(String(route.params.id),controller.signal,batch.value||undefined,kind.value==='author'?'authors':'institutions');if(current===generation){detail.value=value;batch.value=value.batch_id}}
    else{const value=await searchGraphEntities(query.value,kind.value,batch.value,controller.signal);if(current===generation){items.value=value.items;truncated.value=value.truncated;batch.value=value.batch_id}}
  }catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'读取失败'}
  finally{if(current===generation)loading.value=false}
}
async function search(){if(route.params.id)await router.push({path:kind.value==='author'?'/research/authors':'/research/institutions',query:{batch_id:batch.value,q:query.value}});else await load()}
watch(()=>[route.path,route.query.batch_id,route.query.q],()=>{batch.value=String(route.query.batch_id??'');query.value=String(route.query.q??'');items.value=[];void load()},{immediate:true})
onBeforeUnmount(()=>{generation++;controller?.abort()})
</script>
<template><section class="standard-page"><div class="page-heading"><div><h1>{{kind==='author'?'作者证据画像':'机构证据画像'}}</h1><p>当前仅展示 C 已交付的节点与有证据邻居；不推断合作统计或永久任职。</p></div><RouterLink :to="{path:'/research/graph',query:{batch_id:batch}}" class="text-button">返回同批图谱</RouterLink></div><section class="panel profile-panel"><form @submit.prevent="search"><label>{{kind==='author'?'作者':'机构'}}名称<input v-model="query" class="form-input"/></label><label>发布批次<input v-model="batch" class="form-input"/></label><button class="button button-secondary" :disabled="loading">检索</button></form><StatePanel v-if="loading" kind="loading" title="正在读取 C 图谱"/><StatePanel v-else-if="error" kind="error" title="画像暂不可用" :description="error" retry @retry="load"/><CGraphDetail v-else-if="detail" :detail="detail" @navigate="drawer=$event"/><template v-else><p class="small-note">批次 {{batch}} · {{items.length}} 个节点 {{truncated?'（已截断，请缩小关键词）':''}}</p><RouterLink v-for="item in items" :key="item.id" class="related-paper" :to="{path:`/research/${kind==='author'?'authors':'institutions'}/${encodeURIComponent(item.id)}`,query:{batch_id:batch}}">{{item.name}}</RouterLink><p v-if="!items.length" class="small-note">当前批次未找到该类型节点。</p></template></section><DetailDrawer :id="drawer" source="c" :batch-id="batch" @close="drawer=null" @navigate="id=>drawer=id" @explore="router.push({path:'/research/graph',query:{batch_id:batch,seed:$event}})"/></section></template>
<style scoped>.profile-panel{padding:24px}.profile-panel form{display:flex;gap:15px;align-items:end;margin-bottom:20px}.profile-panel label{flex:1;font-size:12px}.profile-panel .form-input{margin-top:8px}.related-paper{margin-top:12px}@media(max-width:700px){.profile-panel form{flex-direction:column;align-items:stretch}}</style>

