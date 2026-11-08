<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {compareDataBatches,getJob,type BatchComparison,type JobInfo} from '../services/admin.ts'

const props=defineProps<{jobs:JobInfo[]}>()
const choices=computed(()=>props.jobs.filter(job=>job.kind!=='archive'))
const first=ref(0),second=ref(0),busy=ref(false),error=ref('')
const result=ref<BatchComparison|null>(null),details=ref<JobInfo[]>([])
let generation=0
const sourceName=(s:string)=>({openalex:'OpenAlex',cvf:'CVF',ecva:'ECVA',dblp:'DBLP'} as Record<string,string>)[s]??s
const statusName=(s:string)=>({succeeded:'已完成',partial:'需处理',failed:'失败',queued:'等待中',running:'导入中'} as Record<string,string>)[s]??s
const number=(value:number|null|undefined)=>value==null?'—':value.toLocaleString('zh-CN')
function label(job:JobInfo){return `#${job.id} · ${job.venue} ${job.year} · ${sourceName(job.source)} · ${job.created_at.slice(0,16).replace('T',' ')}`}
function completeness(index:number,key:'with_abstract'|'with_doi'|'with_authors'){
  const quality=details.value[index]?.quality
  return quality?.total?`${(quality[key]/quality.total*100).toFixed(1)}%（${quality[key]}/${quality.total}）`:'—'
}
const rows=computed(()=>{
  if(!result.value)return []
  const a=result.value.first,b=result.value.second
  return [
    {label:'成功处理',values:[number(a.succeeded),number(b.succeeded)]},
    {label:'新增论文',values:[number(a.new_papers),number(b.new_papers)]},
    {label:'重复论文',values:[number(a.duplicate_papers),number(b.duplicate_papers)]},
    {label:'处理失败',values:[number(a.failed),number(b.failed)]},
    {label:'批次论文数',values:[number(a.paper_count),number(b.paper_count)]},
    {label:'摘要完整率',values:[completeness(0,'with_abstract'),completeness(1,'with_abstract')]},
    {label:'DOI 完整率',values:[completeness(0,'with_doi'),completeness(1,'with_doi')]},
    {label:'作者完整率',values:[completeness(0,'with_authors'),completeness(1,'with_authors')]},
  ]
})
const scopesDiffer=computed(()=>result.value&&(result.value.first.venue!==result.value.second.venue||result.value.first.year!==result.value.second.year||result.value.first.source!==result.value.second.source))
async function compare(){
  if(!first.value||!second.value||first.value===second.value)return
  const current=++generation
  busy.value=true;error.value='';result.value=null;details.value=[]
  try{
    const [comparison,left,right]=await Promise.all([compareDataBatches(first.value,second.value),getJob(first.value),getJob(second.value)])
    if(current!==generation)return
    result.value=comparison;details.value=[left,right]
  }catch(e){if(current===generation)error.value=e instanceof Error?e.message:'无法读取批次对比，请重试'}
  finally{if(current===generation)busy.value=false}
}
watch([first,second],()=>{generation++;result.value=null;details.value=[];error.value='';busy.value=false},{flush:'sync'})
watch(choices,list=>{
  if(list.length<2){first.value=list[0]?.id??0;second.value=0;return}
  if(list.some(j=>j.id===first.value)&&list.some(j=>j.id===second.value))return
  const latest=list[0]!
  const previous=list.slice(1).find(j=>j.venue===latest.venue&&j.year===latest.year&&j.source===latest.source)??list[1]!
  first.value=previous.id;second.value=latest.id
  void compare()
},{immediate:true})
</script>

<template>
<section class="panel comparison-panel" aria-labelledby="batch-comparison-heading">
  <header class="comparison-heading"><div><div class="eyebrow">IMPORT COMPARISON</div><h2 id="batch-comparison-heading">批次对比</h2><p>对比两次导入的处理结果和论文信息完整情况。</p></div><span class="comparison-badge">{{choices.length}} 个可选批次</span></header>
  <p v-if="choices.length<2" class="empty-comparison">至少完成两次导入后，可以在这里对比批次。</p>
  <template v-else>
    <div class="comparison-controls">
      <label>基准批次<select v-model.number="first" class="form-input" aria-label="基准批次"><option v-for="item in choices" :key="item.id" :value="item.id" :disabled="item.id===second">{{label(item)}}</option></select></label>
      <span class="versus" aria-hidden="true">VS</span>
      <label>对比批次<select v-model.number="second" class="form-input" aria-label="对比批次"><option v-for="item in choices" :key="item.id" :value="item.id" :disabled="item.id===first">{{label(item)}}</option></select></label>
      <button class="button button-primary" :disabled="busy||!first||!second||first===second" @click="compare">{{busy?'正在读取…':'开始对比'}}</button>
    </div>
    <p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <p v-else-if="busy" class="comparison-message" role="status">正在读取所选批次…</p>
    <div v-else-if="result" aria-live="polite">
      <p v-if="scopesDiffer" class="comparison-message scope-note">两个批次的会议、年份或来源不同，请结合各自范围查看结果。</p>
      <div class="comparison-table"><table><thead><tr><th scope="col">对比指标</th><th scope="col">基准 · #{{result.first.id}}<small>{{result.first.venue}} {{result.first.year}} · {{sourceName(result.first.source)}} · {{statusName(result.first.status)}}</small></th><th scope="col">对比 · #{{result.second.id}}<small>{{result.second.venue}} {{result.second.year}} · {{sourceName(result.second.source)}} · {{statusName(result.second.status)}}</small></th></tr></thead><tbody><tr v-for="row in rows" :key="row.label"><th scope="row">{{row.label}}</th><td>{{row.values[0]}}</td><td>{{row.values[1]}}</td></tr></tbody></table></div>
      <div class="overlap-summary"><span>两批共有论文 <strong>{{number(result.shared_papers)}}</strong></span><span>仅基准批次 <strong>{{number(result.only_first)}}</strong></span><span>仅对比批次 <strong>{{number(result.only_second)}}</strong></span></div>
      <p class="comparison-footnote">新增与重复按导入时的记录统计，完整率按批次当前关联论文统计；未记录或没有论文时显示“—”。</p>
    </div>
    <p v-else class="comparison-message">已更改批次，点击“开始对比”查看结果。</p>
  </template>
</section>
</template>

<style scoped>
.comparison-panel{padding:24px;margin-bottom:20px}.comparison-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:22px}.comparison-heading h2{font-size:18px;color:#365965;margin:6px 0 8px}.comparison-heading p,.comparison-message,.empty-comparison{font-size:12px;color:#789099;line-height:1.8}.comparison-badge{font-size:11px;color:#368576;background:#edf7f3;border-radius:20px;padding:7px 12px;white-space:nowrap}.comparison-controls{display:grid;grid-template-columns:minmax(0,1fr) 24px minmax(0,1fr) auto;align-items:end;gap:16px;margin-bottom:20px}.comparison-controls label{display:flex;flex-direction:column;gap:9px;font-size:12px;color:#66818a;min-width:0}.comparison-controls select{width:100%;text-overflow:ellipsis}.versus{align-self:center;padding-top:22px;color:#99b1b7;font-size:11px;font-weight:600}.comparison-table{overflow:auto;border:1px solid #e4edef;border-radius:10px}.comparison-table table{width:100%;border-collapse:collapse;min-width:470px;font-size:12px;table-layout:fixed}.comparison-table th,.comparison-table td{padding:12px 18px;border-bottom:1px solid #edf2f3;text-align:left}.comparison-table thead th{background:#f4f8f9;color:#496b76;font-weight:600}.comparison-table thead th:first-child{width:30%}.comparison-table th small{display:block;font-size:10px;font-weight:400;color:#819aa4;margin-top:6px;line-height:1.6}.comparison-table tbody th{font-weight:400;color:#708992}.comparison-table td{color:#355c68;font-weight:600}.comparison-table td:last-child{background:#f7fbf9;color:#238575}.comparison-table tr:last-child th,.comparison-table tr:last-child td{border-bottom:0}.overlap-summary{display:flex;gap:20px;flex-wrap:wrap;margin-top:16px;padding:14px 18px;border-radius:9px;background:#f5f9f8;font-size:11px;color:#739087}.overlap-summary strong{font-size:16px;color:#338573;margin-left:8px}.comparison-footnote{font-size:10px;color:#94a7ae;line-height:1.8;margin:12px 0 0}.scope-note{margin:0 0 12px}.empty-comparison{margin-bottom:0}@media(max-width:900px){.comparison-controls{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.versus{display:none}.comparison-controls>.button{grid-column:1/-1;justify-self:start}}@media(max-width:600px){.comparison-panel{padding:18px}.comparison-controls{grid-template-columns:minmax(0,1fr)}.comparison-heading{flex-wrap:wrap}.comparison-table th,.comparison-table td{padding:12px}.overlap-summary{gap:12px}}
</style>
