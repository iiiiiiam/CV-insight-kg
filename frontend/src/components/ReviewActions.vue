<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {auth} from '../stores/auth.ts'
import {ApiError} from '../services/http.ts'
import {STATUS_LABELS,submitKnowledgeReview} from '../services/knowledge.ts'
import type {DisplayCandidate,KnowledgeDetail,ReviewAction} from '../services/knowledge.ts'
const props=defineProps<{detail:KnowledgeDetail;item:DisplayCandidate}>()
const emit=defineEmits<{saved:[candidateId:string,affected:number];busy:[value:boolean];reload:[];focus:[candidateId:string]}>()
const reason=ref(''),name=ref(''),busy=ref(false),blocked=ref(false),error=ref('')
const endpoints=computed(()=>props.item.entity?[]:props.detail.review.items.filter(item=>'key' in item.content&&[props.item.source,props.item.target].includes(item.content.key)))
const endpointsReady=computed(()=>!!props.item.entity||(endpoints.value.length===2&&endpoints.value.every(item=>item.status==='confirmed')))
const disabled=computed(()=>busy.value||blocked.value||!reason.value.trim())
watch(()=>`${props.detail.snapshot_revision}:${props.item.candidate_id}`,()=>{
  reason.value='';name.value=props.item.entity?.name??'';error.value='';blocked.value=false
},{immediate:true})
async function act(action:ReviewAction){
  if(disabled.value)return
  busy.value=true;emit('busy',true);error.value=''
  try{
    const body={paper_id:props.detail.paper.openalex_id,candidate_id:props.item.candidate_id,
      action,reason:reason.value.trim(),snapshot_revision:props.detail.snapshot_revision,
      ...(action==='correct'?{name:name.value.trim()}:{}),
    }
    const result=await submitKnowledgeReview(body,auth.session?.csrf_token??'')
    emit('saved',body.candidate_id,result.affected_candidate_ids.length)
  }catch(e){
    error.value=e instanceof ApiError?e.message:'未能取得保存结果，请重新读取存档后核对，避免重复提交。'
    if(!(e instanceof ApiError)||e.status===409||e.status>=500)blocked.value=true
    if(e instanceof ApiError&&e.status===401)auth.session=null
  }finally{busy.value=false;emit('busy',false)}
}
</script>
<template><section class="review-actions" aria-label="当前记录审核操作"><h3>审核当前记录</h3><p>当前账号：{{auth.session?.username}} · {{STATUS_LABELS[item.status]}}。证据只读，保存后与 B 工具共用同一份存档。</p>
  <div v-if="!item.entity" class="endpoint-check"><strong>关系两端实体</strong><div v-for="endpoint in endpoints" :key="endpoint.candidate_id"><span>{{'name' in endpoint.content?endpoint.content.name:endpoint.candidate_id}} · {{STATUS_LABELS[endpoint.status]}}</span><button class="text-button" :disabled="busy" @click="emit('focus',endpoint.candidate_id)">定位该实体</button></div><p v-if="!endpointsReady">请先分别确认两端实体，才能确认关系。</p></div>
  <label class="form-label" for="review-reason">操作理由（必填）</label><textarea id="review-reason" v-model="reason" rows="3" maxlength="2000" :disabled="busy||blocked" placeholder="请填写你核对原文后的实际判断理由"></textarea>
  <template v-if="item.entity&&item.status==='pending'"><label class="form-label" for="review-name">实体显示名称</label><input id="review-name" v-model="name" class="form-input" maxlength="300" :disabled="busy||blocked"/><p>改名后仍待审核，需要另行确认；不改变原文、实体身份或类别。</p></template>
  <div class="action-buttons"><template v-if="item.status==='pending'"><button class="button button-primary" :disabled="disabled||!endpointsReady" @click="act('confirm')">确认该记录</button><button class="button button-secondary" :disabled="disabled" @click="act('reject')">驳回该记录</button><button v-if="item.entity" class="button button-secondary" :disabled="disabled||!name.trim()||name.trim()===item.entity.name" @click="act('correct')">保存显示名</button></template><button v-else class="button button-secondary" :disabled="disabled" @click="act('reopen')">撤回决定，重新审核</button></div>
  <p v-if="item.entity&&item.status==='confirmed'">撤回已确认实体时，相关已确认关系也会退回待审核，并保留历史。</p>
  <p v-if="busy" role="status">正在校验并保存…</p><p v-if="error" class="inline-error" role="alert">{{error}}</p><button v-if="blocked" class="text-button" @click="emit('reload')">重新读取存档</button>
</section></template>
<style scoped>.review-actions{margin-top:24px;padding:20px;border:1px solid #dce9e5;border-radius:8px;background:#f7fbfa}.review-actions h3{font-size:14px}.review-actions p{font-size:12px;line-height:1.8;color:#6e8490;margin-top:10px}.review-actions textarea{width:100%;resize:vertical;border:1px solid #d7e5e2;border-radius:6px;padding:10px;font:inherit;color:#385d66}.action-buttons{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}.endpoint-check{margin-top:15px;font-size:12px}.endpoint-check>div{display:flex;justify-content:space-between;gap:12px;align-items:start;margin-top:10px;overflow-wrap:anywhere}.endpoint-check>div .text-button{flex-shrink:0}.review-actions .inline-error{color:#a35f53}</style>
