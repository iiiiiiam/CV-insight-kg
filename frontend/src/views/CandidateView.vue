<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import StatePanel from '../components/StatePanel.vue'
import AppIcon from '../components/AppIcon.vue'
import ReviewActions from '../components/ReviewActions.vue'
import KnowledgeDownloads from '../components/KnowledgeDownloads.vue'
import {ACTION_LABELS,STATUS_LABELS,candidateLabel,candidateRows,evidenceExcerpt,getKnowledgeDetail,getKnowledgeOverview} from '../services/knowledge.ts'
import type {CandidateKind,KnowledgeDetail,KnowledgeOverview,ReviewStatus,ViewMode} from '../services/knowledge.ts'
import {safeSourceUrl} from '../services/research.ts'

const route=useRoute(),router=useRouter()
const overview=ref<KnowledgeOverview|null>(null),detail=ref<KnowledgeDetail|null>(null)
const loading=ref(false),detailLoading=ref(false),error=ref(''),detailError=ref('')
const kind=ref<CandidateKind>('entities'),mode=ref<ViewMode>('reviewed'),status=ref<ReviewStatus|'all'>('all')
const selectedId=ref(''),evidenceIndex=ref(0)
const saving=ref(false),notice=ref('')
const reviewEnabled=computed(()=>route.meta.reviewEnabled===true)
const statuses:ReviewStatus[]=['pending','confirmed','rejected']
let overviewGeneration=0,detailGeneration=0,controller:AbortController|undefined,overviewController:AbortController|undefined
const paperId=computed(()=>String(route.query.paper_id??''))
const candidates=computed(()=>detail.value?candidateRows(detail.value,kind.value,mode.value,status.value):[])
const selected=computed(()=>candidates.value.find(c=>c.candidate_id===selectedId.value))
const evidence=computed(()=>selected.value?.evidence[evidenceIndex.value])
const excerpt=computed(()=>{
  if(!evidence.value||!detail.value||evidence.value.field==='metadata')return null
  return evidenceExcerpt(detail.value.paper[evidence.value.field]??'',evidence.value)
})
function resetSelection(){selectedId.value=candidates.value[0]?.candidate_id??'';evidenceIndex.value=0}
async function focusCandidate(id:string){kind.value='entities';mode.value='reviewed';status.value='all';await nextTick();selectedId.value=id}
async function saved(id:string,affected:number){
  notice.value=affected>1?'已保存；相关记录的联动变化也已记录。':'已保存到 B 审核存档。'
  status.value='all';mode.value='reviewed';await loadOverview();await nextTick()
  if(candidates.value.some(c=>c.candidate_id===id))selectedId.value=id
}
async function loadDetail(){
  const current=++detailGeneration;controller?.abort();detail.value=null;selectedId.value='';detailError.value=''
  if(!paperId.value||!overview.value){detailLoading.value=false;return}
  controller=new AbortController();detailLoading.value=true
  try{
    const value=await getKnowledgeDetail(paperId.value,controller.signal,overview.value.snapshot_revision)
    if(current!==detailGeneration)return
    detail.value=value;resetSelection()
  }catch(e){if(current===detailGeneration&&!(e instanceof DOMException&&e.name==='AbortError'))detailError.value=e instanceof Error?e.message:'候选读取失败'}
  finally{if(current===detailGeneration)detailLoading.value=false}
}
async function loadOverview(){
  const current=++overviewGeneration
  overviewController?.abort();controller?.abort();detailGeneration++
  loading.value=true;detailLoading.value=false;error.value='';detailError.value=''
  overview.value=null;detail.value=null;selectedId.value=''
  overviewController=new AbortController()
  try{
    const value=await getKnowledgeOverview(overviewController.signal)
    if(current!==overviewGeneration)return
    overview.value=value
    if(!paperId.value&&value.papers[0])await router.replace({path:route.path,query:{paper_id:value.papers[0].openalex_id}})
    else await loadDetail()
  }catch(e){if(current===overviewGeneration&&!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'B 快照读取失败'}
  finally{if(current===overviewGeneration)loading.value=false}
}
watch(paperId,()=>void loadDetail())
watch([kind,mode,status],resetSelection)
watch(selectedId,()=>{evidenceIndex.value=0})
onMounted(loadOverview)
onBeforeUnmount(()=>{overviewGeneration++;detailGeneration++;controller?.abort();overviewController?.abort()})
</script>

<template>
  <section class="standard-page candidate-page">
    <div class="page-heading"><div><div class="eyebrow">B · KNOWLEDGE & REVIEW</div><h1>{{reviewEnabled?'审核与改名':'候选与审核结果'}}</h1><p>{{reviewEnabled?'核对证据后，使用登录账号保存确认、驳回、改名或撤回决定。':'查看原始抽取、B 存档中的审核状态、纠正内容和操作历史。'}}</p></div><button class="button button-secondary" :disabled="loading||saving" @click="loadOverview"><AppIcon name="refresh"/>重新读取存档</button></div>
    <p v-if="notice" class="inline-success" role="status">{{notice}}</p>
    <div class="mock-banner api-banner"><AppIcon name="info"/><span>B 审核结果与 C 发布快照独立；审核后须手动生成、导入、校验并发布，研究图谱才会更新。提及不等于使用或验证。</span></div>
    <StatePanel v-if="loading" kind="loading" title="正在校验 B 输入与审核存档"/>
    <StatePanel v-else-if="error" kind="error" title="B 数据读取或校验失败" :description="error" retry @retry="loadOverview"/>
    <template v-else-if="overview">
      <div class="candidate-summary"><span>{{overview.papers.length}} 篇论文</span><span>{{overview.entity_count}} 个原始实体候选</span><span>{{overview.relation_count}} 条原始关系候选</span></div>
      <div class="status-overview"><div v-for="s in statuses" :key="s" :class="s"><strong>{{STATUS_LABELS[s]}}</strong><span>实体 {{overview.review_counts[s].entities}} · 关系 {{overview.review_counts[s].relations}}</span></div></div>
      <section class="panel candidate-card snapshot-info">
        <label class="form-label" for="b-paper">选择固定快照中的论文</label>
        <select id="b-paper" :value="paperId" :disabled="saving" class="form-input" @change="router.replace({path:route.path,query:{paper_id:($event.target as HTMLSelectElement).value}})"><option v-for="paper in overview.papers" :key="paper.openalex_id" :value="paper.openalex_id">{{paper.title}}</option></select>
        <p class="small-note">{{overview.dataset_id}} · {{overview.schema_version}} · {{overview.rule_version}} · {{overview.vocabulary_version}}</p>
        <p class="small-note mono">快照指纹 {{overview.snapshot_revision}}</p><p class="small-note">读取时间 {{new Date(overview.loaded_at).toLocaleString('zh-CN')}}</p>
      </section>
      <StatePanel v-if="detailLoading" kind="loading" title="正在读取候选、审核状态与历史"/>
      <StatePanel v-else-if="detailError" kind="error" title="无法读取该论文，或数据已变化" :description="detailError" retry @retry="loadOverview"/>
      <template v-else-if="detail">
        <section class="panel candidate-card view-options">
          <label>查看内容<select v-model="mode" :disabled="saving" class="form-input"><option value="reviewed">当前审核结果</option><option value="original">原始抽取（全部待审）</option></select></label>
          <label>状态筛选<select v-model="status" :disabled="saving" class="form-input"><option value="all">全部状态</option><option v-for="s in statuses" :key="s" :value="s">{{STATUS_LABELS[s]}}</option></select></label>
          <p class="small-note">{{detail.review.has_archive?'已读取 B 审核存档；原始抽取单独保留。':'该论文尚无审核存档，按原始待审核状态展示。'}}<br/><RouterLink v-if="!reviewEnabled" :to="{path:'/admin/reviews/edit',query:{paper_id:paperId}}" class="text-button">进入审核与改名</RouterLink><span v-else>仅在“当前审核结果”中操作；证据只读。</span></p>
        </section>
        <div class="candidate-grid">
          <section class="panel candidate-card">
            <div class="candidate-tabs"><button :class="{active:kind==='entities'}" :disabled="saving" @click="kind='entities'">实体</button><button :class="{active:kind==='relations'}" :disabled="saving" @click="kind='relations'">关系</button><small>{{candidates.length}} 条符合条件</small></div>
            <div class="candidate-list"><button v-for="item in candidates" :key="item.candidate_id" class="candidate-row" :class="{selected:selectedId===item.candidate_id}" :disabled="saving" @click="selectedId=item.candidate_id"><span class="badge badge-outline" :class="item.status">{{STATUS_LABELS[item.status]}}</span><strong>{{candidateLabel(detail,item,mode)}}</strong><small>{{item.entity?.kind??item.kind}} · {{item.evidence.length}} 条证据</small><small v-if="item.changed_fields.length" class="correction-note">已纠正：{{item.changed_fields.join('、')}}；来源原文保持原样</small></button></div>
            <StatePanel v-if="!candidates.length" kind="empty" title="当前筛选下没有记录" description="原始抽取仅含待审核候选；可切换查看内容或状态。"/>
            <ReviewActions v-if="reviewEnabled&&mode==='reviewed'&&selected" :detail="detail" :item="selected" @saved="saved" @busy="saving=$event" @reload="loadOverview" @focus="focusCandidate"/>
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
              <a v-if="safeSourceUrl(evidence.source_url)" :href="safeSourceUrl(evidence.source_url)??undefined" target="_blank" rel="noopener noreferrer" class="text-button">查看证据来源<AppIcon name="external" :size="15"/></a>
            </template><StatePanel v-else kind="empty" title="请选择记录查看证据"/>
          </section>
        </div>
        <section class="panel candidate-card review-history"><h2>该论文的审核历史（{{detail.review.history.length}}）</h2>
          <p class="small-note">D 页面新提交使用当前登录账号；历史仍包含 B 工具记录，不能将全部历史视为经过 D 认证。自动化测试记录不计作真人确认。</p>
          <p v-if="!detail.review.history.length" class="small-note">暂无审核操作；D 不会自动生成确认或历史。</p>
          <article v-for="event in detail.review.history" :key="event.sequence" class="history-event"><strong>#{{event.sequence}} · {{ACTION_LABELS[event.action]??event.action}}</strong><p>{{event.reviewer}} · {{new Date(event.occurred_at).toLocaleString('zh-CN')}}</p><p>理由：{{event.reason}}</p><small>{{STATUS_LABELS[event.before.status]}} → {{STATUS_LABELS[event.after.status]}}</small><p class="small-note mono">{{event.after.candidate_id}}</p><details><summary>查看操作前后内容与证据</summary><pre>{{JSON.stringify({before:event.before,after:event.after},null,2)}}</pre></details></article>
          <p class="small-note mono">存档指纹 {{detail.review.archive_revision??'无存档'}}</p>
        </section>
        <section class="panel candidate-card diagnostics"><h2>诊断信息（{{detail.result.diagnostics.length}}）</h2><ul v-if="detail.result.diagnostics.length"><li v-for="(item,index) in detail.result.diagnostics" :key="index">{{item}}</li></ul><p v-else class="small-note">B 未返回诊断信息。</p><p class="small-note">{{detail.notice}}</p></section>
      </template>
      <KnowledgeDownloads :revision="overview.snapshot_revision" :disabled="saving"/>
    </template>
  </section>
</template>

<style scoped>
.candidate-page{padding-bottom:30px}.candidate-summary{display:flex;gap:24px;flex-wrap:wrap;margin:20px 0;color:#397c71;font-weight:600}.status-overview{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}.status-overview>div{padding:12px 16px;background:white;border:1px solid #dde8e5;border-radius:8px;display:flex;gap:15px}.status-overview span{font-size:12px}.pending{color:#8a6528}.confirmed{color:#237d62}.rejected{color:#a35656}.candidate-grid{display:grid;grid-template-columns:minmax(260px,.9fr) minmax(320px,1.1fr);gap:20px;margin-top:20px}.candidate-card{padding:24px;min-width:0}.candidate-card h2{margin-bottom:18px}.snapshot-info .small-note{margin-top:12px;overflow-wrap:anywhere}.view-options{display:flex;align-items:end;gap:20px;margin-top:20px}.view-options label{min-width:180px;font-size:12px}.view-options select{margin-top:8px}.candidate-tabs{display:flex;gap:8px;align-items:center;margin-bottom:16px}.candidate-tabs button{padding:10px 16px;border:1px solid #dce8e6;background:#fff;border-radius:6px}.candidate-tabs .active{background:#e9f5f1;color:#237d6a}.candidate-tabs small{color:#718995}.candidate-list{max-height:650px;overflow:auto}.candidate-row{width:100%;display:block;padding:15px 12px;border:1px solid #e5ecef;border-radius:7px;background:#fff;text-align:left;margin-bottom:9px}.candidate-row.selected{background:#edf7f4;border-color:#8bc8ba}.candidate-row strong{display:block;margin:10px 0 6px;overflow-wrap:anywhere}.candidate-row small,.candidate-card li{font-size:12px;color:#6e8791;line-height:1.8}.candidate-row .correction-note{display:block;color:#956b26}.candidate-card ul{padding-left:18px}.evidence-card .mono{overflow-wrap:anywhere;word-break:break-all}.evidence-card blockquote{margin:20px 0;padding:14px;border-left:3px solid #63a894;background:#f0f7f5;white-space:pre-wrap;overflow-wrap:anywhere}.original-text{font-size:13px;line-height:1.8;padding-top:12px;white-space:pre-wrap;overflow-wrap:anywhere}.candidate-card pre{max-height:360px;overflow:auto;font-size:11px;padding:12px;background:#f5f8f9;white-space:pre-wrap;overflow-wrap:anywhere}.diagnostics,.review-history{margin-top:20px}.evidence-card .text-button{margin-top:20px}.history-event{padding:16px 0;border-bottom:1px solid #edf2f4}.history-event p{margin:8px 0;font-size:12px;line-height:1.7;overflow-wrap:anywhere}.history-event small{font-size:12px;color:#708591}.history-event details{font-size:12px}@media(max-width:900px){.candidate-grid{grid-template-columns:1fr}.view-options{align-items:stretch;flex-direction:column}}
</style>
