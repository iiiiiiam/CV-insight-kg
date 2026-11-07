<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {auth} from '../stores/auth.ts'
import {getFeedbackQueue,resolveFeedback,reopenFeedback,KIND_NAMES,RELATION_NAMES} from '../services/knowledge-feedback.ts'
import type {FeedbackQueue,FeedbackRecord} from '../services/knowledge-feedback.ts'
const queue=ref<FeedbackQueue|null>(null),selectedId=ref(''),filter=ref('open'),error=ref(''),notice=ref(''),busy=ref(false)
const action=ref('dismiss'),reason=ref(''),name=ref(''),kind=ref('method'),source=ref(''),aliases=ref('')
const labels:Record<string,string>={open:'待处理',resolved:'已处理',dismissed:'已说明保留'}
const rows=computed(()=>queue.value?.requests.filter(r=>filter.value==='all'||r.status===filter.value)??[])
const selected=computed(()=>queue.value?.requests.find(r=>r.id===selectedId.value))
const content=computed(()=>selected.value?.context.content as Record<string,string>|undefined)
const proofs=computed(()=>Array.isArray(selected.value?.context.evidence)?selected.value!.context.evidence as Array<{field:string;quote:string}>:[])
const targetName=computed(()=>selected.value?.term??content.value?.name??RELATION_NAMES[content.value?.kind??'']??'关联条目')
const impact=computed(()=>({
  dismiss:'保留公共知识，只关闭这条反馈，不修改名称或关联。',
  rename:'修改这篇论文中此对象的公共显示名称。其他用户刷新知识页后可见；原文和引用不变。',
  exclude:content.value?.name?'从这篇论文的公共知识中移除此对象及相关连线。其他用户刷新后可见。':'从这篇论文的公共知识中移除此关联，保留对象。其他用户刷新后可见。',
  add_term:'补充公共词表，对当前输入重新识别；同一规则可用于后续交接的新论文。',
}[action.value]??''))
const saveLabel=computed(()=>({dismiss:'保留结果并关闭',rename:'保存公共名称',exclude:'移除公共条目',add_term:'加入词表并重新识别'}[action.value]??'保存处理结果'))
async function load(){busy.value=true;error.value='';try{queue.value=await getFeedbackQueue();if(!queue.value.requests.some(r=>r.id===selectedId.value))selectedId.value=''}catch(e){queue.value=null;error.value=e instanceof Error?e.message:'反馈读取失败'}finally{busy.value=false}}
function pick(r:FeedbackRecord){selectedId.value=r.id;reason.value='';name.value=r.term??String((r.context.content as Record<string,unknown>|undefined)?.name??'');aliases.value=r.term??'';source.value='';action.value=r.term?'add_term':'dismiss';error.value='';notice.value=''}
async function save(){
  if(!selected.value||!queue.value)return
  busy.value=true;error.value='';notice.value=''
  try{
    const summary=reason.value.trim()||({dismiss:'保留原结果，关闭反馈。',rename:`修改公共显示名称为：${name.value.trim()}`,exclude:'从当前论文公共结果中移除反馈条目。',add_term:`加入公共词条：${name.value.trim()}`} as Record<string,string>)[action.value]!
    await resolveFeedback(selected.value.id,{revision:queue.value.revision,action:action.value,reason:summary,
      ...(action.value==='rename'?{name:name.value}:{}),
      ...(action.value==='add_term'?{name:name.value,kind:kind.value,source_url:source.value,aliases:aliases.value.split('\n').map(a=>a.trim()).filter(Boolean)}:{})},auth.session?.csrf_token??'')
    notice.value='处理已保存，知识阅读页刷新后可看到本轮结果；已发布图谱仍按原发布版本读取。';await load()
  }catch(e){error.value=e instanceof Error?e.message:'处理失败，请刷新核对后再试';busy.value=false}
}
async function reopen(){
  if(!selected.value||!queue.value||busy.value)return
  const identifier=selected.value.id
  busy.value=true;error.value='';notice.value=''
  try{
    await reopenFeedback(identifier,queue.value.revision,auth.session?.csrf_token??'')
    filter.value='open';await load()
    const request=queue.value?.requests.find(r=>r.id===identifier)
    if(request)pick(request)
    notice.value='处理已撤回，反馈已回到待处理；本次处理产生的公共修正已取消，知识页刷新后生效。'
  }catch(e){error.value=e instanceof Error?e.message:'撤回处理失败，请刷新后重试。';busy.value=false}
}
onMounted(load)
</script>
<template><section class="standard-page"><div class="page-heading"><div><h1>用户反馈处理</h1><p>只处理用户主动提交的问题，已撤回的反馈不显示。</p></div><button class="button button-secondary" :disabled="busy" @click="load">刷新反馈</button></div>
  <p v-if="error" class="inline-error" role="alert">{{error}}</p><p v-if="notice" class="inline-success" role="status">{{notice}}</p><p v-if="busy" role="status">正在读取或保存…</p>
  <template v-if="queue"><div class="feedback-counts"><button v-for="s in ['open','resolved','dismissed']" :key="s" class="panel count-card" :class="{active:filter===s}" @click="filter=s"><strong>{{queue.counts[s as keyof typeof queue.counts]}}</strong><span>{{labels[s]}}</span><div class="bar" :style="{width:queue.counts[s as keyof typeof queue.counts]/Math.max(1,queue.requests.length)*100+'%'}"></div></button></div>
    <div class="feedback-layout"><section class="panel queue-panel"><label>查看范围<select v-model="filter" class="form-input"><option value="all">全部反馈</option><option v-for="(label,s) in labels" :key="s" :value="s">{{label}}</option></select></label><button v-for="r in rows" :key="r.id" class="request-row" :class="{active:selectedId===r.id}" :disabled="busy" @click="pick(r)"><small>{{labels[r.status]}} · {{r.term?'遗漏名称':'内容问题'}}</small><strong>{{r.term??r.paper_title}}</strong><span>{{r.message}}</span></button><p v-if="!rows.length">当前范围没有反馈。</p></section>
    <section class="panel handling-panel"><template v-if="selected"><h2>{{selected.paper_title}}</h2><div class="target-card"><strong>{{selected.term?'遗漏名称':KIND_NAMES[content?.kind??'']??'关联'}}：{{targetName}}</strong><p>用户反馈：{{selected.message}}</p><blockquote v-for="(proof,index) in proofs" :key="index">{{proof.field==='title'?'标题':proof.field==='abstract'?'摘要':'来源字段'}}：{{proof.quote}}</blockquote><blockquote v-if="selected.term">原文片段：{{selected.context.quote}}</blockquote></div><a :href="'/research/knowledge?paper_id='+encodeURIComponent(selected.paper_id)" target="_blank" rel="noopener noreferrer" class="text-button">打开对应论文与完整依据 ↗</a><details><summary>更多原始记录</summary><pre>{{JSON.stringify(selected.context,null,2)}}</pre></details>
      <form v-if="selected.status==='open'" @submit.prevent="save"><label>处理方式<select v-model="action" class="form-input" :disabled="busy"><option value="dismiss">核对后保留原结果，说明原因</option><template v-if="selected.candidate_id"><option value="exclude">不采纳此条信息</option><option v-if="'content' in selected.context&&selected.context.content&&typeof selected.context.content==='object'&&'name' in selected.context.content" value="rename">纠正显示名称</option></template><option v-if="selected.term" value="add_term">核实后加入词表并重新识别</option></select></label>
        <label v-if="action==='rename'||action==='add_term'">{{action==='add_term'?'规范名称':'显示名称'}}<input v-model="name" class="form-input" maxlength="200" required :disabled="busy"/></label>
        <template v-if="action==='add_term'"><label>类别<select v-model="kind" class="form-input" :disabled="busy"><option value="method">方法</option><option value="dataset">数据集</option><option value="task">任务</option><option value="topic">主题</option></select></label><label>必要别名（每行一个，包含原文写法）<textarea v-model="aliases" rows="3" required :disabled="busy"></textarea></label><label>公开依据地址<input v-model="source" type="url" class="form-input" maxlength="2000" required :disabled="busy"/></label><p class="small-note">核实类别与歧义后再补词；别名会作用于当前全部输入，不能只为演示论文填答案。</p></template>
        <div class="impact-note"><strong>保存后会怎样？</strong><p>{{impact}}</p><p>不会改 A 的原始论文，也不会自动更新 C 已发布的图谱。</p></div><details><summary>补充处理说明（选填）</summary><textarea v-model="reason" rows="2" maxlength="2000" placeholder="不填写时，系统会记录本次实际执行的操作。" :disabled="busy"></textarea></details><button class="button button-primary" :disabled="busy">{{saveLabel}}</button></form>
      <div v-else-if="selected.resolution"><h3>处理记录</h3><p>{{selected.resolution.reviewer}} · {{selected.resolution.occurred_at}}</p><p>{{selected.resolution.reason}}</p><div class="impact-note"><p>撤回会取消这次处理产生的公共改名、移除或补词效果，并将反馈重新放回待处理。原处理记录保留在历史中。</p><button type="button" class="button button-secondary" :disabled="busy" @click="reopen">撤回处理，重新待处理</button></div><details><summary>处理前后内容</summary><pre>{{JSON.stringify(selected.resolution,null,2)}}</pre></details></div>
      <details v-if="selected.processing_history?.length"><summary>已撤回的处理历史（{{selected.processing_history.length}}）</summary><article v-for="(event,index) in selected.processing_history" :key="index"><p>原处理：{{event.resolution.reviewer}} · {{event.resolution.reason}}</p><p>撤回：{{event.reopened_by}} · {{event.reopened_at}}</p></article></details>
    </template><p v-else>选择一条用户反馈，先核对原文，再作出处理。</p></section></div>
    <section class="panel terms"><h2>通过反馈补充的词条（{{queue.terms.length}}）</h2><p v-if="!queue.terms.length">暂无补充词条。</p><article v-for="t in queue.terms" :key="t.term.kind+':'+t.term.name"><strong>{{t.term.name}}</strong> · {{t.term.kind}}<p>{{t.term.aliases.join(' / ')}}</p><a :href="t.source_url" target="_blank" rel="noopener noreferrer">公开依据</a></article></section>
  </template></section></template>
<style scoped>
.target-card,.impact-note{padding:16px;background:#f0f7f3;border:1px solid #d0e2d6;border-radius:8px;margin:18px 0;font-size:15px;line-height:1.8}.target-card p,.impact-note p{margin:10px 0;white-space:pre-wrap}.target-card blockquote{margin:12px 0;padding:10px;border-left:3px solid #7daa94;overflow-wrap:anywhere}.handling-panel .button,.standard-page>.page-heading .button{font-size:15px;min-height:44px;padding:10px 18px}.handling-panel .form-input{font-size:15px}.handling-panel>.text-button{font-size:15px;display:inline-block;padding:8px 0}.request-row{font-size:15px}.feedback-counts{display:flex;gap:16px;margin:24px 0}.count-card{padding:18px;flex:1;text-align:left;min-width:0;border:1px solid #dce8e5}.count-card strong{display:block;font-size:28px}.count-card span{font-size:15px}.bar{height:5px;background:#72b09a;margin-top:12px}.active{background:#edf8f3;border-color:#83bca6}.feedback-layout{display:grid;grid-template-columns:minmax(230px,.8fr) minmax(350px,1.2fr);gap:20px}.queue-panel,.handling-panel,.terms{padding:24px;min-width:0}.request-row{display:block;width:100%;text-align:left;margin-top:12px;padding:14px;background:white;border:1px solid #dce8e5;border-radius:8px}.request-row strong,.request-row span{display:block;margin-top:8px;overflow-wrap:anywhere}.request-row small{color:#648075}.handling-panel>p{line-height:1.8;margin:16px 0;white-space:pre-wrap}.handling-panel label,.queue-panel label{display:block;margin:16px 0;font-size:15px}.handling-panel h2{line-height:1.7;overflow-wrap:anywhere}textarea{display:block;width:100%;margin-top:8px;padding:10px;border:1px solid #cedfd7;border-radius:6px;font:inherit}.handling-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6faf8;padding:12px;font-size:12px;max-height:400px;overflow:auto}.handling-panel details{margin:18px 0;font-size:15px}.terms{margin-top:24px}.terms article{margin-top:14px;padding:12px;border-top:1px solid #e3ece8}@media(max-width:850px){.feedback-layout{grid-template-columns:1fr}.feedback-counts{flex-wrap:wrap}}</style>
