<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import StatePanel from '../components/StatePanel.vue'
import AppIcon from '../components/AppIcon.vue'
import {evidenceExcerpt,getKnowledgeDetail,getKnowledgeOverview} from '../services/knowledge.ts'
import type {Candidate,KnowledgeDetail,KnowledgeOverview} from '../services/knowledge.ts'
import {safeSourceUrl} from '../services/research.ts'

const route=useRoute(),router=useRouter()
const overview=ref<KnowledgeOverview|null>(null),detail=ref<KnowledgeDetail|null>(null)
const loading=ref(false),detailLoading=ref(false),error=ref(''),detailError=ref('')
const kind=ref<'entities'|'relations'>('entities'),selected=ref<Candidate|null>(null),evidenceIndex=ref(0)
let generation=0,controller:AbortController|undefined,overviewController:AbortController|undefined
const paperId=computed(()=>String(route.query.paper_id??''))
const candidates=computed(()=>detail.value?.result[kind.value]??[])
const evidence=computed(()=>selected.value?.evidence[evidenceIndex.value])
const excerpt=computed(()=>{
  if(!evidence.value||!detail.value||evidence.value.field==='metadata')return null
  return evidenceExcerpt(detail.value.paper[evidence.value.field]??'',evidence.value)
})
function candidateLabel(item:Candidate){
  if(item.entity)return item.entity.name
  const names=new Map(detail.value?.result.entities.map(c=>[c.entity?.key,c.entity?.name]))
  return `${names.get(item.source)??item.source} → ${item.kind} → ${names.get(item.target)??item.target}`
}
function pick(item:Candidate){selected.value=item;evidenceIndex.value=0}
async function loadDetail(){
  const current=++generation;controller?.abort();detail.value=null;selected.value=null;detailError.value=''
  if(!paperId.value){detailLoading.value=false;return}
  controller=new AbortController();detailLoading.value=true
  try{
    const value=await getKnowledgeDetail(paperId.value,controller.signal)
    if(current!==generation)return
    detail.value=value;selected.value=value.result[kind.value][0]??null;evidenceIndex.value=0
  }catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))detailError.value=e instanceof Error?e.message:'候选读取失败'}
  finally{if(current===generation)detailLoading.value=false}
}
async function loadOverview(){
  loading.value=true;error.value='';overviewController?.abort();overviewController=new AbortController()
  try{
    overview.value=await getKnowledgeOverview(overviewController.signal)
    if(!paperId.value&&overview.value.papers[0])await router.replace({path:route.path,query:{paper_id:overview.value.papers[0].openalex_id}})
    else await loadDetail()
  }catch(e){if(!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'B 快照读取失败'}
  finally{loading.value=false}
}
watch(paperId,()=>void loadDetail())
watch(kind,()=>{selected.value=candidates.value[0]??null;evidenceIndex.value=0})
onMounted(loadOverview)
onBeforeUnmount(()=>{controller?.abort();overviewController?.abort()})
</script>

<template>
  <section class="standard-page candidate-page">
    <div class="page-heading"><div><div class="eyebrow">B · KNOWLEDGE CANDIDATES</div><h1>候选与证据查看</h1><p>B 已交付抽取代码的真实输出，保留全部 pending 状态。</p></div><button class="button button-secondary" @click="loadOverview"><AppIcon name="refresh"/>刷新</button></div>
    <div class="mock-banner api-banner"><AppIcon name="info"/><span>来自已校验的固定 20 篇快照；与 A 当前数据库独立。提及不等于使用或验证，审核写入与 C 正式图谱待接入。</span></div>
    <StatePanel v-if="loading" kind="loading" title="正在读取 B 的真实抽取结果"/>
    <StatePanel v-else-if="error" kind="error" title="B 快照读取失败" :description="error" retry @retry="loadOverview"/>
    <template v-else-if="overview">
      <div class="candidate-summary"><span>{{overview.papers.length}} 篇论文</span><span>{{overview.entity_count}} 个实体候选</span><span>{{overview.relation_count}} 条关系候选</span><span>已确认 {{overview.confirmed_count}}</span></div>
      <section class="panel candidate-card snapshot-info">
        <label class="form-label" for="b-paper">选择固定快照中的论文</label>
        <select id="b-paper" :value="paperId" class="form-input" @change="router.replace({path:route.path,query:{paper_id:($event.target as HTMLSelectElement).value}})"><option v-for="paper in overview.papers" :key="paper.openalex_id" :value="paper.openalex_id">{{paper.title}}</option></select>
        <p class="small-note">{{overview.dataset_id}} · {{overview.schema_version}} · {{overview.rule_version}} · {{overview.vocabulary_version}}</p>
      </section>
      <StatePanel v-if="detailLoading" kind="loading" title="正在读取论文候选与证据"/>
      <StatePanel v-else-if="detailError" kind="error" title="无法读取该论文的 B 候选" :description="detailError" retry @retry="loadDetail"/>
      <template v-else-if="detail">
        <div class="candidate-grid">
          <section class="panel candidate-card">
            <div class="candidate-tabs"><button :class="{active:kind==='entities'}" @click="kind='entities'">实体 {{detail.result.entities.length}}</button><button :class="{active:kind==='relations'}" @click="kind='relations'">关系 {{detail.result.relations.length}}</button></div>
            <div class="candidate-list"><button v-for="item in candidates" :key="item.candidate_id" class="candidate-row" :class="{selected:selected?.candidate_id===item.candidate_id}" @click="pick(item)"><span class="badge badge-outline">{{item.status}} · 待审核</span><strong>{{candidateLabel(item)}}</strong><small>{{item.entity?.kind??item.kind}} · {{item.evidence.length}} 条证据</small></button></div>
            <StatePanel v-if="!candidates.length" kind="empty" title="该类别没有候选" description="显示 B 实际输出，不补造实体或关系。"/>
          </section>
          <section class="panel candidate-card evidence-card">
            <h2>原文证据</h2>
            <template v-if="selected&&evidence">
              <p class="small-note mono">{{selected.candidate_id}}</p>
              <label class="form-label" for="evidence-index">证据条目</label><select id="evidence-index" v-model.number="evidenceIndex" class="form-input"><option v-for="(item,index) in selected.evidence" :key="index" :value="index">{{index+1}} · {{item.field}}</option></select>
              <dl class="definition-list"><dt>字段</dt><dd>{{evidence.field}}</dd><dt>论文 ID</dt><dd class="mono">{{evidence.paper_id}}</dd><dt>文本区间</dt><dd>{{evidence.start===null?'不适用（元数据）':`[${evidence.start}, ${evidence.end}) · Unicode 字符`}}</dd><dt>元数据路径</dt><dd class="mono">{{JSON.stringify(evidence.path)}}</dd><dt>输入指纹</dt><dd class="mono">{{evidence.input_fingerprint}}</dd></dl>
              <blockquote>{{evidence.quote}}</blockquote>
              <details v-if="excerpt"><summary>查看原文与证据高亮</summary><p class="original-text">{{excerpt.before}}<mark>{{excerpt.quote}}</mark>{{excerpt.after}}</p></details>
              <p v-else-if="evidence.field!=='metadata'" class="inline-error">证据区间与原文不匹配，请联系 B 核查。</p>
              <details v-else><summary>查看原始元数据</summary><pre>{{JSON.stringify({openalex_id:detail.paper.openalex_id,year:detail.paper.year,venue:detail.paper.venue,authorships:detail.paper.authorships},null,2)}}</pre></details>
              <a v-if="safeSourceUrl(evidence.source_url)" :href="safeSourceUrl(evidence.source_url)!" target="_blank" rel="noopener noreferrer" class="text-button">查看证据来源<AppIcon name="external" :size="15"/></a>
            </template><StatePanel v-else kind="empty" title="请选择候选查看证据"/>
          </section>
        </div>
        <section class="panel candidate-card diagnostics"><h2>诊断信息（{{detail.result.diagnostics.length}}）</h2><ul v-if="detail.result.diagnostics.length"><li v-for="(item,index) in detail.result.diagnostics" :key="index">{{item}}</li></ul><p v-else class="small-note">B 未返回诊断信息。</p><p class="small-note">{{detail.notice}}</p></section>
      </template>
    </template>
  </section>
</template>

<style scoped>
.candidate-page{padding-bottom:30px}.candidate-summary{display:flex;gap:24px;flex-wrap:wrap;margin:20px 0;color:#397c71;font-weight:600}.candidate-grid{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(320px,1.1fr);gap:20px;margin-top:20px}.candidate-card{padding:24px;min-width:0}.candidate-card h2{margin-bottom:18px}.snapshot-info .small-note{margin-top:14px;overflow-wrap:anywhere}.candidate-tabs{display:flex;gap:8px;margin-bottom:16px}.candidate-tabs button{padding:10px 16px;border:1px solid #dce8e6;background:#fff;border-radius:6px}.candidate-tabs .active{background:#e9f5f1;color:#237d6a}.candidate-list{max-height:650px;overflow:auto}.candidate-row{width:100%;display:block;padding:15px 12px;border:1px solid #e5ecef;border-radius:7px;background:#fff;text-align:left;margin-bottom:9px}.candidate-row.selected{background:#edf7f4;border-color:#8bc8ba}.candidate-row strong{display:block;margin:10px 0 6px;overflow-wrap:anywhere}.candidate-row small,.candidate-card li{font-size:12px;color:#6e8791;line-height:1.8}.candidate-card ul{padding-left:18px}.evidence-card .mono{overflow-wrap:anywhere;word-break:break-all}.evidence-card blockquote{margin:20px 0;padding:14px;border-left:3px solid #63a894;background:#f0f7f5;white-space:pre-wrap;overflow-wrap:anywhere}.original-text{font-size:13px;line-height:1.8;padding-top:12px;white-space:pre-wrap;overflow-wrap:anywhere}.evidence-card pre{max-height:360px;overflow:auto;font-size:11px;padding:12px;background:#f5f8f9;white-space:pre-wrap;overflow-wrap:anywhere}.diagnostics{margin-top:20px}.evidence-card .text-button{margin-top:20px}@media(max-width:900px){.candidate-grid{grid-template-columns:1fr}}
</style>
