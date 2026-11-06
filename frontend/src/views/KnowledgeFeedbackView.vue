<script setup lang="ts">
import {computed,onMounted,ref} from 'vue'
import {auth} from '../stores/auth.ts'
import {getFeedbackQueue,resolveFeedback} from '../services/knowledge-feedback.ts'
import type {FeedbackQueue,FeedbackRecord} from '../services/knowledge-feedback.ts'
const queue=ref<FeedbackQueue|null>(null),selectedId=ref(''),filter=ref('open'),error=ref(''),notice=ref(''),busy=ref(false)
const action=ref('dismiss'),reason=ref(''),name=ref(''),kind=ref('method'),source=ref(''),aliases=ref('')
const labels:Record<string,string>={open:'待处理',resolved:'已处理',dismissed:'已说明保留'}
const rows=computed(()=>queue.value?.requests.filter(r=>filter.value==='all'||r.status===filter.value)??[])
const selected=computed(()=>queue.value?.requests.find(r=>r.id===selectedId.value))
async function load(){busy.value=true;error.value='';try{queue.value=await getFeedbackQueue();if(!queue.value.requests.some(r=>r.id===selectedId.value))selectedId.value=''}catch(e){queue.value=null;error.value=e instanceof Error?e.message:'反馈读取失败'}finally{busy.value=false}}
function pick(r:FeedbackRecord){selectedId.value=r.id;reason.value='';name.value=r.term??'';aliases.value=r.term??'';source.value='';action.value=r.term?'add_term':'dismiss';error.value='';notice.value=''}
async function save(){
  if(!selected.value||!queue.value)return
  busy.value=true;error.value='';notice.value=''
  try{
    await resolveFeedback(selected.value.id,{revision:queue.value.revision,action:action.value,reason:reason.value,
      ...(action.value==='rename'?{name:name.value}:{}),
      ...(action.value==='add_term'?{name:name.value,kind:kind.value,source_url:source.value,aliases:aliases.value.split('\n').map(a=>a.trim()).filter(Boolean)}:{})},auth.session?.csrf_token??'')
    notice.value='处理已保存，知识阅读页刷新后可看到本轮结果；已发布图谱仍按原发布版本读取。';await load()
  }catch(e){error.value=e instanceof Error?e.message:'处理失败，请刷新核对后再试';busy.value=false}
}
onMounted(load)
</script>
<template><section class="standard-page"><div class="page-heading"><div><h1>用户反馈处理</h1><p>只处理用户提交的问题，不把全部知识列为待审核任务。</p></div><button class="button button-secondary" :disabled="busy" @click="load">刷新反馈</button></div>
  <p v-if="error" class="inline-error" role="alert">{{error}}</p><p v-if="notice" class="inline-success" role="status">{{notice}}</p><p v-if="busy" role="status">正在读取或保存…</p>
  <template v-if="queue"><div class="feedback-counts"><button v-for="s in ['open','resolved','dismissed']" :key="s" class="panel count-card" :class="{active:filter===s}" @click="filter=s"><strong>{{queue.counts[s as keyof typeof queue.counts]}}</strong><span>{{labels[s]}}</span><div class="bar" :style="{width:queue.counts[s as keyof typeof queue.counts]/Math.max(1,queue.requests.length)*100+'%'}"></div></button></div>
    <div class="feedback-layout"><section class="panel queue-panel"><label>查看范围<select v-model="filter" class="form-input"><option value="all">全部反馈</option><option v-for="(label,s) in labels" :key="s" :value="s">{{label}}</option></select></label><button v-for="r in rows" :key="r.id" class="request-row" :class="{active:selectedId===r.id}" :disabled="busy" @click="pick(r)"><small>{{labels[r.status]}} · {{r.term?'遗漏名称':'内容问题'}}</small><strong>{{r.term??r.paper_title}}</strong><span>{{r.message}}</span></button><p v-if="!rows.length">当前范围没有反馈。</p></section>
    <section class="panel handling-panel"><template v-if="selected"><h2>{{selected.paper_title}}</h2><p>{{selected.message}}</p><p v-if="selected.term">申请识别：{{selected.term}}</p><a :href="'/research/knowledge?paper_id='+encodeURIComponent(selected.paper_id)" target="_blank" rel="noopener noreferrer" class="text-button">打开知识与原文</a><details><summary>反馈时的内容与证据</summary><pre>{{JSON.stringify(selected.context,null,2)}}</pre></details>
      <form v-if="selected.status==='open'" @submit.prevent="save"><label>处理方式<select v-model="action" class="form-input" :disabled="busy"><option value="dismiss">核对后保留原结果，说明原因</option><template v-if="selected.candidate_id"><option value="exclude">不采纳此条信息</option><option v-if="'content' in selected.context&&selected.context.content&&typeof selected.context.content==='object'&&'name' in selected.context.content" value="rename">纠正显示名称</option></template><option v-if="selected.term" value="add_term">核实后加入词表并重新识别</option></select></label>
        <label v-if="action==='rename'||action==='add_term'">{{action==='add_term'?'规范名称':'显示名称'}}<input v-model="name" class="form-input" maxlength="200" required :disabled="busy"/></label>
        <template v-if="action==='add_term'"><label>类别<select v-model="kind" class="form-input" :disabled="busy"><option value="method">方法</option><option value="dataset">数据集</option><option value="task">任务</option><option value="topic">主题</option></select></label><label>必要别名（每行一个，包含原文写法）<textarea v-model="aliases" rows="3" required :disabled="busy"></textarea></label><label>公开依据地址<input v-model="source" type="url" class="form-input" maxlength="2000" required :disabled="busy"/></label><p class="small-note">核实类别与歧义后再补词；别名会作用于当前全部输入，不能只为演示论文填答案。</p></template>
        <label>处理理由<textarea v-model="reason" rows="3" maxlength="2000" required :disabled="busy"></textarea></label><button class="button button-primary" :disabled="busy||!reason.trim()">保存处理结果</button></form>
      <div v-else-if="selected.resolution"><h3>处理记录</h3><p>{{selected.resolution.reviewer}} · {{selected.resolution.occurred_at}}</p><p>{{selected.resolution.reason}}</p><details><summary>处理前后内容</summary><pre>{{JSON.stringify(selected.resolution,null,2)}}</pre></details></div>
    </template><p v-else>选择一条用户反馈，先核对原文，再作出处理。</p></section></div>
    <section class="panel terms"><h2>通过反馈补充的词条（{{queue.terms.length}}）</h2><p v-if="!queue.terms.length">暂无补充词条。</p><article v-for="t in queue.terms" :key="t.term.kind+':'+t.term.name"><strong>{{t.term.name}}</strong> · {{t.term.kind}}<p>{{t.term.aliases.join(' / ')}}</p><a :href="t.source_url" target="_blank" rel="noopener noreferrer">公开依据</a></article></section>
  </template></section></template>
<style scoped>.feedback-counts{display:flex;gap:16px;margin:24px 0}.count-card{padding:18px;flex:1;text-align:left;min-width:0;border:1px solid #dce8e5}.count-card strong{display:block;font-size:28px}.count-card span{font-size:13px}.bar{height:5px;background:#72b09a;margin-top:12px}.active{background:#edf8f3;border-color:#83bca6}.feedback-layout{display:grid;grid-template-columns:minmax(230px,.8fr) minmax(350px,1.2fr);gap:20px}.queue-panel,.handling-panel,.terms{padding:24px;min-width:0}.request-row{display:block;width:100%;text-align:left;margin-top:12px;padding:14px;background:white;border:1px solid #dce8e5;border-radius:8px}.request-row strong,.request-row span{display:block;margin-top:8px;overflow-wrap:anywhere}.request-row small{color:#648075}.handling-panel>p{line-height:1.8;margin:16px 0;white-space:pre-wrap}.handling-panel label,.queue-panel label{display:block;margin:16px 0;font-size:13px}.handling-panel h2{line-height:1.7;overflow-wrap:anywhere}textarea{display:block;width:100%;margin-top:8px;padding:10px;border:1px solid #cedfd7;border-radius:6px;font:inherit}.handling-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6faf8;padding:12px;font-size:12px;max-height:400px;overflow:auto}.handling-panel details{margin:18px 0}.terms{margin-top:24px}.terms article{margin-top:14px;padding:12px;border-top:1px solid #e3ece8}@media(max-width:850px){.feedback-layout{grid-template-columns:1fr}.feedback-counts{flex-wrap:wrap}}</style>
