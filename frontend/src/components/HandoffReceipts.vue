<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue'
import {getReceipts,type ReceiptData} from '../services/admin.ts'
const props=defineProps<{id:number;state?:string|null}>()
const data=ref<ReceiptData|null>(null),error=ref(''),busy=ref(false);let generation=0
const label=(s:string)=>({received:'已接收',processed:'已处理',failed:'处理失败'} as Record<string,string>)[s]??s
async function load(){const v=++generation;busy.value=true;error.value='';try{const value=await getReceipts(props.id);if(v===generation)data.value=value}catch(e){if(v===generation)error.value=String(e)}finally{if(v===generation)busy.value=false}}
watch(()=>[props.id,props.state],()=>{data.value=null;void load()},{immediate:true});onUnmounted(()=>generation++)
</script>
<template><section class="receipt-panel"><header><h3>下游交接状态</h3><button class="text-button" :disabled="busy" @click="load">刷新交接状态</button></header><p v-if="error" role="alert">{{error}}</p><template v-if="data"><p v-if="!data.items.some(i=>i.current)">当前版本尚无下游回执。导出和 A 入库完成不代表下游已处理。</p><article v-for="(item,i) in data.items" :key="i"><strong>{{item.recipient}} · {{label(item.status)}}{{item.current?'':'（历史版本）'}}</strong><p>{{item.message}}</p><small v-if="item.snapshot_revision">快照 {{item.snapshot_revision}}</small></article></template></section></template>
<style scoped>.receipt-panel{border-top:1px solid #e1eaea;padding:18px 0;font-size:12px}.receipt-panel header{display:flex;gap:16px;justify-content:space-between;align-items:center}.receipt-panel p{line-height:1.8;color:#789099;margin:12px 0}.receipt-panel article{padding:12px 0;overflow-wrap:anywhere}.receipt-panel small{color:#789099}</style>
