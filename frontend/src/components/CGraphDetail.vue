<script setup lang="ts">
import {nextTick,onBeforeUnmount,ref,watch} from 'vue'
import type {CDetail} from '../types.ts'
const props=defineProps<{detail:CDetail}>(),emit=defineEmits<{navigate:[id:string]}>()
const container=ref<HTMLElement|null>(null),error=ref('')
let generation=0
watch(()=>props.detail,async detail=>{
  const current=++generation;error.value='';await nextTick()
  try{
    const moduleUrl='/api/components/c-paper-detail.js'
    const component=await import(/* @vite-ignore */ moduleUrl)
    if(current===generation&&container.value)component.mountPaperDetail(container.value,detail,(id:string)=>emit('navigate',id))
  }catch{if(current===generation)error.value='C 详情组件加载失败，请检查 D 后端并重新打开详情。'}
},{immediate:true})
onBeforeUnmount(()=>{generation++;container.value?.replaceChildren()})
</script>
<template><div class="c-graph-detail"><p class="small-note">此处的关系和证据来自当前选定的发布批次。</p><p v-if="error" class="inline-error" role="alert">{{error}}</p><div ref="container"></div></div></template>
<style scoped>.c-graph-detail :deep(h1){font-size:22px;line-height:1.7;overflow-wrap:anywhere;margin:12px 0}.c-graph-detail :deep(h2){font-size:14px;margin:24px 0 12px}.c-graph-detail :deep(p){font-size:12px;line-height:1.9;color:#587681;white-space:pre-wrap;overflow-wrap:anywhere}.c-graph-detail :deep(.meta){display:flex;flex-direction:column;gap:8px;font-size:11px;color:#80939e}.c-graph-detail :deep(details){font-size:12px;line-height:1.8;margin:15px 0;border:1px solid #e3ece8;border-radius:7px;padding:12px;overflow-wrap:anywhere}.c-graph-detail :deep(blockquote){margin:10px 0;padding:12px;background:#f1f8f5;border-left:2px solid #8db9ac;white-space:pre-wrap}.c-graph-detail :deep(a),.c-graph-detail :deep(button){color:#197f70}.c-graph-detail :deep(button){padding:6px 10px;background:white;border:1px solid #cfe2dd;border-radius:5px;margin:10px 0}.c-graph-detail :deep(small){color:#8397a0;font-size:11px}</style>
