<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {EMPTY_FILTERS} from '../types.ts'
import {rawResearch} from '../services/research.ts'
import {graphResearch} from '../services/graph.ts'
import {knowledgePaperIdFromGraphId,researchResultQuery,safeResearchReturn} from '../services/research-navigation.ts'
import DetailDrawer from '../components/DetailDrawer.vue'
import StatePanel from '../components/StatePanel.vue'
import AppIcon from '../components/AppIcon.vue'

const route=useRoute(),router=useRouter(),id=ref<string|null>(null),error=ref(''),loading=ref(false)
const source=ref<'a'|'c'>('c'),batch=ref('')
const resultQuery=computed(()=>researchResultQuery(route.query))
const resultLocation=computed(()=>({path:source.value==='a'?'/research/raw-papers':'/research/papers',query:resultQuery.value}))
let controller:AbortController|undefined

function openPaper(next:string){void router.push({path:'/research/papers/'+encodeURIComponent(next),query:{...route.query,source:'a'}})}
function explore(seed:string){void router.push({path:'/research/papers',query:{...resultQuery.value,batch_id:batch.value||undefined,seed}})}
async function resolveKnowledgeId(requested:string){
  const direct=knowledgePaperIdFromGraphId(requested)
  if(direct)return direct
  const detail=await graphResearch.getDetail(requested,controller?.signal,batch.value,'papers')
  batch.value=detail.batch_id
  return [detail.node.source_id,detail.node.source_url,detail.node.id]
    .map(value=>knowledgePaperIdFromGraphId(value??'')).find(Boolean)??''
}
async function resolve(){
  controller?.abort();controller=new AbortController();error.value='';id.value=null
  let requested=String(route.params.id)
  source.value=route.query.source==='a'||/^\d+$/.test(requested)?'a':'c';batch.value=String(route.query.batch_id??'')
  loading.value=true
  try{
    if(requested==='first'){
      const page=await (source.value==='a'?rawResearch:graphResearch).getPapers({...EMPTY_FILTERS,batch_id:batch.value},controller.signal)
      if(!page.items[0])throw new Error('当前查询范围没有论文。')
      requested=page.items[0].id;batch.value=page.batch_id
    }
    if(source.value==='c'){
      const paperId=await resolveKnowledgeId(requested)
      if(!paperId)throw new Error('C论文节点没有可关联到B单篇知识的OpenAlex ID。')
      const fallback=router.resolve({path:'/research/papers',query:resultQuery.value}).fullPath
      await router.replace({path:'/research/knowledge',query:{paper_id:paperId,from:'research',batch_id:batch.value,
        return_to:safeResearchReturn(route.query.return_to)??fallback}})
      return
    }
    id.value=requested
  }catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'无法读取论文'}
  finally{if(!controller.signal.aborted)loading.value=false}
}
watch(()=>[route.params.id,route.query.batch_id,route.query.source],()=>void resolve(),{immediate:true})
onBeforeUnmount(()=>controller?.abort())
</script>

<template>
  <section class="standard-page">
    <div class="page-heading"><div><div class="eyebrow">PAPER DETAIL</div><h1>{{source==='a'?'A原始论文详情':'正在进入知识与证据'}}</h1>
      <p>{{source==='a'?'保留A原始论文元数据入口':'公共论文统一使用知识、证据与个人调整页面'}}</p></div>
      <RouterLink :to="resultLocation" class="button button-secondary"><AppIcon name="arrow"/>返回检索结果</RouterLink></div>
    <StatePanel v-if="loading" kind="loading" title="正在打开单篇论文"/>
    <StatePanel v-else-if="error" kind="error" title="无法打开论文" :description="error" retry @retry="resolve"/>
    <template v-else-if="source==='a'">
      <div class="panel paper-detail-background"><AppIcon name="book" :size="48"/><p>A原始论文详情已在右侧展开。</p></div>
      <DetailDrawer :id="id" type="Paper" source="a" @close="router.push(resultLocation)" @paper="openPaper" @navigate="openPaper" @explore="explore"/>
    </template>
  </section>
</template>
