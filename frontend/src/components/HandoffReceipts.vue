<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue'
import {getReceipts,type ReceiptData} from '../services/admin.ts'
import {retryTask} from '../services/workflows.ts'
const props=defineProps<{id:number;state?:string|null}>()
const data=ref<ReceiptData|null>(null),error=ref(''),busy=ref(false);let generation=0
let timer:ReturnType<typeof setTimeout>|undefined
const taskLabel=(s:string)=>({queued:'等待自动交接',running:'正在自动交接',succeeded:'B 已接收',failed:'交接暂未完成'} as Record<string,string>)[s]??s
async function retryDelivery(){const task=data.value?.automatic_task;if(!task)return;try{await retryTask('handoffs',task.id);await load()}catch(e){error.value=String(e)}}
const label=(s:string)=>({received:'已接收',processed:'已处理',failed:'处理失败'} as Record<string,string>)[s]??s
async function load(){clearTimeout(timer);const v=++generation;busy.value=true;error.value='';try{const value=await getReceipts(props.id);if(v===generation)data.value=value}catch(e){if(v===generation)error.value=String(e)}finally{if(v===generation){busy.value=false;const t=data.value?.automatic_task;if(!t||t.status==='queued'||t.status==='running'||t.next_attempt_at)timer=setTimeout(()=>void load(),3000)}}}
watch(()=>[props.id,props.state],()=>{data.value=null;void load()},{immediate:true});onUnmounted(()=>{generation++;clearTimeout(timer)})
</script>
<template><section class="receipt-panel"><header><h3>下游交接状态</h3><button class="text-button" :disabled="busy" @click="load">刷新交接状态</button></header><p v-if="error" role="alert">{{error}}</p><template v-if="data"><article v-if="data.automatic_task"><strong>{{taskLabel(data.automatic_task.status)}}</strong><p v-if="data.automatic_task.next_attempt_at">稍后自动重试 · {{new Date(data.automatic_task.next_attempt_at+'Z').toLocaleString('zh-CN')}}</p><p v-if="data.automatic_task.error">{{data.automatic_task.error}}</p><button v-if="data.automatic_task.status==='failed'" class="text-button" :disabled="busy" @click="retryDelivery">立即重试交接</button></article><p v-else-if="!data.items.some(i=>i.current)">批次导入成功后会自动交接给 B。</p><article v-for="(item,i) in data.items" :key="i"><strong>{{item.recipient}} · {{label(item.status)}}{{item.current?'':'（历史版本）'}}</strong><p>{{item.message}}</p><small v-if="item.snapshot_revision">快照 {{item.snapshot_revision}}</small></article></template></section></template>
<style scoped>.receipt-panel{border-top:1px solid #e1eaea;padding:18px 0;font-size:12px}.receipt-panel header{display:flex;gap:16px;justify-content:space-between;align-items:center}.receipt-panel p{line-height:1.8;color:#789099;margin:12px 0}.receipt-panel article{padding:12px 0;overflow-wrap:anywhere}.receipt-panel small{color:#789099}</style>
