<script setup lang="ts">
import {onBeforeUnmount,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {EMPTY_FILTERS} from '../types.ts'
import {rawResearch} from '../services/research.ts'
import {graphResearch} from '../services/graph.ts'
import DetailDrawer from '../components/DetailDrawer.vue'
import StatePanel from '../components/StatePanel.vue'
import AppIcon from '../components/AppIcon.vue'
const route=useRoute(),router=useRouter(),id=ref<string|null>(null),error=ref('')
const source=ref<'a'|'c'>('c'),batch=ref('')
let controller:AbortController|undefined
async function resolve(){
  controller?.abort();controller=new AbortController();error.value='';id.value=null
  const requested=String(route.params.id)
  source.value=route.query.source==='a'||/^\d+$/.test(requested)?'a':'c';batch.value=String(route.query.batch_id??'')
  if(requested!=='first'){id.value=requested;return}
  try{
    const page=await (source.value==='a'?rawResearch:graphResearch).getPapers({...EMPTY_FILTERS,batch_id:batch.value},controller.signal)
    if(page.items[0])await router.replace({path:'/research/papers/'+encodeURIComponent(page.items[0].id),query:{source:source.value,batch_id:page.batch_id}})
    else error.value='当前查询范围没有论文。'
  }catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'无法读取论文'}
}
watch(()=>[route.params.id,route.query.batch_id,route.query.source],()=>void resolve(),{immediate:true})
onBeforeUnmount(()=>controller?.abort())
</script>
<template>
  <section class="standard-page"><div class="page-heading"><div><div class="eyebrow">PAPER DETAIL</div><h1>论文详情</h1><p>{{source==='c'?'C 已发布固定批次与逐条证据':'A 原始论文元数据'}}</p></div><RouterLink :to="source==='a'?'/research/raw-papers':{path:'/research/papers',query:{batch_id:batch}}" class="button button-secondary"><AppIcon name="arrow"/>返回列表</RouterLink></div><StatePanel v-if="error" kind="error" title="无法打开论文" :description="error" retry @retry="resolve"/><div v-else class="panel paper-detail-background"><AppIcon name="book" :size="48"/><p>{{id?'详情已在右侧展开。':'正在读取第一篇实际论文…'}}</p></div><DetailDrawer :id="id" type="Paper" :source="source" :batch-id="source==='c'?batch:undefined" @close="router.push(source==='a'?'/research/raw-papers':'/research/papers')" @paper="router.push({path:'/research/papers/'+encodeURIComponent($event),query:{source,batch_id:batch}})" @navigate="(next)=>router.push({path:'/research/papers/'+encodeURIComponent(next),query:{source,batch_id:batch}})" @explore="router.push({path:'/research/graph',query:{batch_id:batch,seed:$event}})"/></section>
</template>
