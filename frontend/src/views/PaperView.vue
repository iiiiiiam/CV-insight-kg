<script setup lang="ts">
import {onBeforeUnmount,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {EMPTY_FILTERS} from '../types.ts'
import {research} from '../services/research.ts'
import DetailDrawer from '../components/DetailDrawer.vue'
import StatePanel from '../components/StatePanel.vue'
import AppIcon from '../components/AppIcon.vue'
const route=useRoute(),router=useRouter(),id=ref<string|null>(null),error=ref('')
let controller:AbortController|undefined
async function resolve(){
  controller?.abort();controller=new AbortController();error.value='';id.value=null
  const requested=String(route.params.id)
  if(requested!=='first'){id.value=requested;return}
  try{
    const page=await research.getPapers(EMPTY_FILTERS,controller.signal)
    if(page.items[0])await router.replace('/research/papers/'+page.items[0].id)
    else error.value='A 当前数据库中没有论文，请先导入固定样本。'
  }catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'无法读取论文'}
}
watch(()=>route.params.id,()=>void resolve(),{immediate:true})
onBeforeUnmount(()=>controller?.abort())
</script>
<template>
  <section class="standard-page"><div class="page-heading"><div><div class="eyebrow">PAPER DETAIL</div><h1>论文详情</h1><p>元数据、导入批次与原始来源。</p></div><RouterLink to="/research/papers" class="button button-secondary"><AppIcon name="arrow"/>返回列表</RouterLink></div><StatePanel v-if="error" kind="error" title="无法打开论文" :description="error" retry @retry="resolve"/><div v-else class="panel paper-detail-background"><AppIcon name="book" :size="48"/><p>{{id?'详情已在右侧展开。':'正在读取第一篇实际论文…'}}</p></div><DetailDrawer :id="id" type="Paper" @close="router.push('/research/papers')" @paper="router.push('/research/papers/'+$event)"/></section>
</template>
