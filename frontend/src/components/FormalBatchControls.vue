<script setup lang="ts">
import {onUnmounted,ref,watch} from 'vue'
import {getBatchWithdrawal,withdrawImportBatch,type BatchWithdrawal} from '../services/admin.ts'
const props=defineProps<{id:number;status:string}>(),emit=defineEmits<{changed:[];pending:[value:boolean]}>()
const batch=ref<BatchWithdrawal|null>(null),reason=ref(''),confirming=ref(false),busy=ref(false),error=ref('')
let generation=0
async function load(){const v=++generation;batch.value=null;error.value='';try{const data=await getBatchWithdrawal(props.id);if(v===generation)batch.value=data}catch(e){if(v===generation)error.value=e instanceof Error?e.message:'批次状态读取失败'}}
async function withdraw(){
 if(!batch.value||!reason.value.trim()||busy.value)return
 const id=props.id,v=generation;busy.value=true;emit('pending',true);error.value=''
 try{const value=await withdrawImportBatch(id,reason.value.trim());if(v===generation){batch.value=value;confirming.value=false;reason.value='';emit('changed')}}
 catch(e){if(v===generation)error.value=e instanceof Error?e.message:'撤回失败'}finally{busy.value=false;emit('pending',false)}
}
watch(()=>[props.id,props.status],()=>{confirming.value=false;reason.value='';void load()},{immediate:true})
onUnmounted(()=>generation++)
</script>
<template><section class="formal-controls" aria-label="批次撤回">
 <p v-if="error" class="inline-error" role="alert">{{error}} <button class="text-button" @click="load">重试读取</button></p>
 <template v-if="batch"><p class="batch-key">{{batch.display_code??batch.batch_code}}</p><p v-if="batch.state==='withdrawn'" class="withdrawn-state">已撤回 · {{batch.withdrawal_reason}}。下方保留该批次导入时的论文记录。</p>
 <template v-else><button v-if="!confirming" class="button button-secondary" :disabled="!batch.can_withdraw||busy" @click="confirming=true">撤回此批次</button><p v-if="batch.blocked_reason">{{batch.blocked_reason}}</p>
 <form v-if="confirming" @submit.prevent="withdraw"><p class="confirm-target">确认撤回 {{batch.display_code??batch.batch_code}}</p><label :for="`withdraw-reason-${id}`">撤回原因</label><textarea :id="`withdraw-reason-${id}`" v-model="reason" class="form-input" required maxlength="2000" :disabled="busy"/><p>撤回后，本批独有论文退出当前论文库；其他有效批次仍提供的论文保留。手动导入的独有论文回到补充库，历史记录和导出保留。</p><div><button class="button button-secondary" :disabled="busy" type="button" @click="confirming=false">取消</button><button class="button button-primary" :disabled="busy||!reason.trim()" type="submit">{{busy?'正在撤回…':'确认撤回'}}</button></div></form></template></template>
</section></template>
<style scoped>.formal-controls{border-top:1px solid #e5edeb;padding:16px 0;font-size:12px;color:#6b858d}.batch-key{overflow-wrap:anywhere;margin-bottom:12px}.withdrawn-state{color:#a76f4b;line-height:1.8}.formal-controls form{max-width:650px}.formal-controls label{display:block;margin-bottom:8px}.formal-controls textarea{width:100%;min-height:80px}.formal-controls form p{margin:10px 0;line-height:1.8}.formal-controls form>div{display:flex;gap:12px}</style>
