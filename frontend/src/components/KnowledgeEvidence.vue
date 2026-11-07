<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,ref,watch} from 'vue'
import {evidenceExcerpt} from '../services/knowledge.ts'
import {safeSourceUrl} from '../services/research.ts'
import {getReading,itemName,KIND_NAMES,sendFeedback} from '../services/knowledge-feedback.ts'
import type {ReadingKnowledge} from '../services/knowledge-feedback.ts'
import type {PersonalKnowledge} from '../services/personal-knowledge.ts'
import {applyPersonal,emptyPersonal,knowledgeGraph,personalAddition,personalKey,readPersonal,resetPersonal,savePersonal,PERSONAL_CHANGE_EVENT} from '../services/personal-knowledge.ts'
import GraphPanel from './GraphPanel.vue'
import MyKnowledgeFeedback from './MyKnowledgeFeedback.vue'
import {feedbackOwner,saveReceipt} from '../services/feedback-receipts.ts'
const props=defineProps<{paperId:string}>()
const base=ref<ReadingKnowledge|null>(null),loading=ref(false),error=ref(''),selectedId=ref(''),proofIndex=ref(0)
const draft=ref<PersonalKnowledge>(emptyPersonal('')),localError=ref(''),localNote=ref('')
const view=computed(()=>base.value?applyPersonal(base.value,draft.value):null)
const graph=computed(()=>view.value?knowledgeGraph(view.value):null)
const editor=ref<'rename'|'add'|null>(null),localName=ref(''),localKind=ref('dataset')
const detailPanel=ref<HTMLElement|null>(null),nameInput=ref<HTMLInputElement|null>(null)
const feedbackForm=ref<HTMLFormElement|null>(null),instanceId=crypto.randomUUID()
const showChanges=ref(false),undoDraft=ref<PersonalKnowledge|null>(null),actionNote=ref('')
const feedbackVersion=ref(0)
const changes=computed(()=>draft.value.hidden.length+Object.keys(draft.value.names).length+draft.value.additions.length)
const originals=computed(()=>base.value?[...base.value.entities,...base.value.relations]:[])
const originalSelected=computed(()=>originals.value.find(item=>item.candidate_id===selectedId.value))
const unhidden=computed(()=>base.value?applyPersonal(base.value,{...draft.value,hidden:[]}):null)
const hiddenItems=computed(()=>draft.value.hidden.map(id=>[...(unhidden.value?.entities??[]),...(unhidden.value?.relations??[])].find(item=>item.candidate_id===id)).filter(item=>!!item))
const collection=ref<'entities'|'relations'>('entities'),form=ref<'item'|'missing'|null>(null)
const message=ref(''),term=ref(''),saving=ref(false),notice=ref('')
const problemType=ref('信息不准确')
let generation=0,controller:AbortController|undefined
const items=computed(()=>view.value?.[collection.value]??[])
const selectedHidden=computed(()=>draft.value.hidden.includes(selectedId.value))
const selected=computed(()=>items.value.find(i=>i.candidate_id===selectedId.value)
  ?? (selectedHidden.value?unhidden.value?.[collection.value].find(i=>i.candidate_id===selectedId.value):undefined))
const proof=computed(()=>selected.value?.evidence[proofIndex.value])
const excerpt=computed(()=>{
  if(!proof.value||!view.value||proof.value.field==='metadata')return null
  return evidenceExcerpt(view.value.paper[proof.value.field]??'',proof.value)
})
async function load(){
  const current=++generation;controller?.abort();controller=new AbortController()
  loading.value=true;error.value='';localError.value='';localNote.value='';base.value=null;form.value=null;editor.value=null;selectedId.value='';undoDraft.value=null;actionNote.value='';showChanges.value=false;feedbackVersion.value=0
  try{const result=await getReading(props.paperId,controller.signal);if(current===generation){base.value=result;readLocal()}}
  catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'知识读取失败'}
  finally{if(current===generation)loading.value=false}
}
watch(()=>props.paperId,()=>{notice.value='';void load()},{immediate:true})
watch([collection,view],()=>{if(!selected.value)selectedId.value=items.value[0]?.candidate_id??''})
watch(selectedId,()=>{proofIndex.value=0;form.value=null;editor.value=null;message.value=''})
function readLocal(){
  if(!base.value)return
  localError.value='';localNote.value=''
  try{const saved=readPersonal(window.localStorage,props.paperId,base.value.revision);draft.value=saved.draft
    if(saved.outdated)localNote.value='公共内容已更新，旧版本个人调整已暂停应用；原记录仍保留。再次调整将保存为当前版本。'
  }catch(e){draft.value=emptyPersonal(base.value.revision);localError.value=e instanceof Error?e.message:'无法读取浏览器存储。'}
}
function store(next:PersonalKnowledge){
  try{savePersonal(window.localStorage,props.paperId,next);undoDraft.value=JSON.parse(JSON.stringify(draft.value));draft.value=next;localError.value='';localNote.value=''
    window.dispatchEvent(new CustomEvent(PERSONAL_CHANGE_EVENT,{detail:{paperId:props.paperId,source:instanceId}}));return true
  }catch{localError.value='浏览器无法保存，本次调整未生效。请检查站点存储是否可用。';return false}
}
function hide(){if(selected.value){const name=itemName(selected.value,view.value!);if(store({...draft.value,hidden:[...new Set([...draft.value.hidden,selected.value.candidate_id])]}))actionNote.value=`已在你的视图中隐藏「${name}」。`}}
function restore(id:string){if(store({...draft.value,hidden:draft.value.hidden.filter(value=>value!==id)}))actionNote.value='已恢复显示。'}
function toggleHidden(){if(selectedHidden.value)restore(selectedId.value);else hide()}
function undoLast(){const previous=undoDraft.value;if(previous&&store(previous)){undoDraft.value=null;actionNote.value='已撤销上一步个人调整。'}}
function reset(){
  try{resetPersonal(window.localStorage,props.paperId);undoDraft.value=JSON.parse(JSON.stringify(draft.value));draft.value=emptyPersonal(base.value!.revision);localError.value='';localNote.value='';editor.value=null;actionNote.value='已恢复默认视图，可撤销本次操作。'
    window.dispatchEvent(new CustomEvent(PERSONAL_CHANGE_EVENT,{detail:{paperId:props.paperId,source:instanceId}}))
  }catch{localError.value='浏览器无法清除个人调整，请检查站点存储。'}
}
async function revealDetail(){
  await nextTick()
  const panel=detailPanel.value;if(!panel)return
  panel.scrollIntoView({block:'nearest',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})
  panel.focus({preventScroll:true})
}
function choose(id:string,kind:'entities'|'relations'=collection.value){
  if(saving.value)return
  collection.value=kind;selectedId.value=id;void revealDetail()
}
async function edit(mode:'rename'|'add'){
  editor.value=mode;localName.value=mode==='rename'&&selected.value&&'name' in selected.value.content?selected.value.content.name:'';form.value=null
  await revealDetail();nameInput.value?.scrollIntoView({block:'nearest'});nameInput.value?.focus({preventScroll:true})
}
function saveEdit(){
  if(!base.value)return
  try{
    const name=localName.value.trim();if(!name||name.length>200)throw new Error('请输入不超过 200 字的名称。')
    let next:PersonalKnowledge
    if(editor.value==='add'){
      const item=personalAddition(localKind.value,name,`personal:${crypto.randomUUID()}`)
      next={...draft.value,additions:[...draft.value.additions,item]}
    }else{
      if(!selected.value)return
      next={...draft.value,names:{...draft.value.names,[selected.value.candidate_id]:name}}
    }
    if(store(next)){editor.value=null;actionNote.value='个人调整已保存，列表与图已同步。'}
  }catch(e){localError.value=e instanceof Error?e.message:'无法保存个人调整。'}
}
function undoName(id=selectedId.value){const names={...draft.value.names};delete names[id];if(store({...draft.value,names}))actionNote.value='已恢复原始显示名称。'}
function removeAddition(){const id=selectedId.value;const names={...draft.value.names};delete names[id]
  if(store({...draft.value,names,additions:draft.value.additions.filter(item=>item.candidate_id!==id),hidden:draft.value.hidden.filter(value=>value!==id&&value!==`${id}:relation`)}))actionNote.value='已移除个人补充，可撤销。'}
function syncLocal(event:Event){
  if(event instanceof StorageEvent){if(event.key===null||event.key===personalKey(props.paperId)){undoDraft.value=null;actionNote.value='';readLocal()}}
  else{const detail=(event as CustomEvent).detail;if(detail?.paperId===props.paperId&&detail.source!==instanceId){undoDraft.value=null;actionNote.value='';readLocal()}}
}
window.addEventListener('storage',syncLocal)
window.addEventListener(PERSONAL_CHANGE_EVENT,syncLocal)
async function openForm(mode:'item'|'missing'){
  form.value=mode;editor.value=null;message.value='';term.value='';notice.value=''
  problemType.value=selected.value&&'source' in selected.value.content?'关联不合适':'信息不准确'
  await nextTick();feedbackForm.value?.scrollIntoView({block:'nearest'});feedbackForm.value?.querySelector('input,textarea')?.scrollIntoView({block:'nearest'})
}
async function submit(){
  if(!base.value||saving.value)return
  const paperId=props.paperId,revision=base.value.revision,current=generation
  const description=(form.value==='missing'?'遗漏名称：'+term.value.trim():problemType.value)+(message.value.trim()?'；'+message.value.trim():'')
  const target=form.value==='missing'?{term:term.value}:{candidate_id:originalSelected.value?.candidate_id}
  saving.value=true;error.value=''
  try{
    const ownerToken=feedbackOwner(window.localStorage)
    const result=await sendFeedback({paper_id:paperId,revision,message:description,owner_token:ownerToken,...target})
    let saved=true
    try{saveReceipt(window.localStorage,paperId,{id:result.id,message:description,status:'open',created_at:new Date().toISOString()})}
    catch{saved=false}
    if(current!==generation)return
    notice.value=`${result.duplicate?'该内容已有待处理反馈':'反馈已提交'}，编号 ${result.id}。`;form.value=null
    if(saved)feedbackVersion.value++
    else notice.value+=' 浏览器未能保存反馈回执，请记下编号；反馈本身已提交。'
  }catch(e){if(current===generation)error.value=e instanceof Error?e.message:'提交失败，请稍后重试'}
  finally{saving.value=false}
}
onBeforeUnmount(()=>{generation++;controller?.abort();window.removeEventListener('storage',syncLocal);window.removeEventListener(PERSONAL_CHANGE_EVENT,syncLocal)})
</script>
<template>
  <section class="knowledge-evidence">
    <header class="section-heading">
      <div><h3>知识与原文依据</h3><p>选择节点或条目，即可查看依据并调整自己的视图。</p></div>
      <button class="action-button" :disabled="loading || saving" @click="load">刷新内容</button>
    </header>
    <p class="privacy-note">个人调整只保存在当前浏览器，不会上报后台；需要公共纠错时再主动反馈。</p>
    <p v-if="loading" role="status">正在读取知识与证据…</p>
    <p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <p v-if="notice" class="inline-success" role="status">{{notice}}</p>
    <p v-if="localError" class="inline-error" role="alert">{{localError}} <button class="action-button" @click="reset">恢复默认</button></p>
    <p v-if="localNote" class="privacy-note" role="status">{{localNote}}</p>
    <template v-if="view">
      <div class="adjustment-bar" aria-label="个人调整工具">
        <div class="bar-buttons">
          <button class="action-button primary-action" @click="edit('add')">＋ 补充个人条目</button>
          <button class="action-button" :disabled="!undoDraft" @click="undoLast">撤销上一步</button>
          <button class="action-button" :aria-expanded="showChanges" @click="showChanges=!showChanges">调整记录（{{changes}}）</button>
          <button class="action-button" :disabled="!changes && !localNote" @click="reset">恢复全部默认</button>
        </div>
        <p v-if="actionNote" class="action-note" role="status">{{actionNote}}</p>
        <div v-if="showChanges" class="change-history">
          <p v-if="!changes">还没有个人调整。</p>
          <div v-for="item in hiddenItems" :key="item.candidate_id" class="change-row">
            <span>已隐藏：{{itemName(item,unhidden!)}}</span>
            <button class="action-button" @click="restore(item.candidate_id)">恢复显示</button>
          </div>
          <div v-for="(name,id) in draft.names" :key="id" class="change-row">
            <span>个人显示名：{{name}}</span>
            <button class="action-button" @click="undoName(String(id))">撤销改名</button>
          </div>
          <p v-if="draft.additions.length">个人补充 {{draft.additions.length}} 项，可选择对应条目后移除。</p>
        </div>
      </div>
      <div class="knowledge-workspace">
        <div class="explorer">
          <section v-if="graph" class="personal-graph" aria-label="本篇论文关联图">
            <h4>本篇论文关联图</h4>
            <GraphPanel :graph="graph" :selected-id="selectedId" @select="node=>choose(node.id,'entities')"/>
          </section>
          <section class="item-browser">
            <div class="collection-tabs" aria-label="条目类型">
              <button class="action-button" :class="{active:collection==='entities'}" :aria-pressed="collection==='entities'" @click="collection='entities'">对象 {{view.entities.length}}</button>
              <button class="action-button" :class="{active:collection==='relations'}" :aria-pressed="collection==='relations'" @click="collection='relations'">关联 {{view.relations.length}}</button>
            </div>
            <div class="item-list">
              <button v-for="item in items" :key="item.candidate_id" class="knowledge-item"
                :class="{active:selectedId===item.candidate_id}" :aria-pressed="selectedId===item.candidate_id"
                :disabled="saving" @click="choose(item.candidate_id)">
                <small>{{'name' in item.content?KIND_NAMES[item.content.kind]:'关联'}}</small>
                <strong>{{itemName(item,view)}}</strong>
              </button>
              <p v-if="!items.length">当前没有可展示的条目。</p>
            </div>
          </section>
        </div>
        <section ref="detailPanel" class="proof-panel" tabindex="-1" aria-label="当前条目详情与操作">
          <template v-if="selected">
            <p class="panel-label">当前选择</p>
            <h4>{{itemName(selected,view)}}</h4>
            <div class="item-actions">
              <button v-if="'name' in selected.content" class="action-button primary-action" @click="edit('rename')">修改显示名称</button>
              <button class="action-button" :aria-pressed="selectedHidden" @click="toggleHidden">{{selectedHidden?'恢复显示此项':'隐藏此项'}}</button>
              <button v-if="draft.names[selectedId]" class="action-button" @click="undoName()">撤销改名</button>
              <button v-if="draft.additions.some(item=>item.candidate_id===selectedId)" class="action-button" @click="removeAddition">移除个人补充</button>
            </div>
            <p v-if="selectedHidden" class="privacy-note" role="status">此项已从你的列表和图中隐藏，详情保留在这里，可随时恢复。</p>
          </template>
          <p v-else>选择图节点或列表条目，查看依据并调整。</p>
          <form v-if="editor" class="edit-form" @submit.prevent="saveEdit">
            <h4>{{editor==='add'?'补充个人条目':'修改个人显示名称'}}</h4>
            <p class="privacy-note">仅改变自己的视图，不发送反馈。</p>
            <label v-if="editor==='add'">类别
              <select v-model="localKind" class="form-input">
                <option v-for="kind in ['topic','method','task','dataset']" :key="kind" :value="kind">{{KIND_NAMES[kind]}}</option>
              </select>
            </label>
            <label>名称<input ref="nameInput" v-model="localName" class="form-input" maxlength="200" required/></label>
            <div class="item-actions">
              <button class="action-button primary-action" :disabled="!localName.trim()">保存个人调整</button>
              <button type="button" class="action-button" @click="editor=null">取消</button>
            </div>
          </form>
          <template v-if="selected">
            <p v-if="draft.names[selectedId]" class="privacy-note">名称按个人设置显示，原文引用保持原样。</p>
            <label v-if="selected.evidence.length">原文依据
              <select v-model.number="proofIndex" class="form-input">
                <option v-for="(p,i) in selected.evidence" :key="i" :value="i">{{i+1}} · {{p.field==='title'?'标题':p.field==='abstract'?'摘要':'来源字段'}} · {{p.quote.length>60?p.quote.slice(0,60)+'…':p.quote}}</option>
              </select>
            </label>
            <template v-if="proof">
              <p v-if="proof.field!=='metadata'&&'name' in selected.content&&proof.quote!==selected.content.name" class="privacy-note">原文写法：{{proof.quote}} → 当前显示名称：{{selected.content.name}}</p>
              <blockquote>{{proof.quote}}</blockquote>
              <p v-if="excerpt" class="source-text">{{excerpt.before}}<mark>{{excerpt.quote}}</mark>{{excerpt.after}}</p>
              <p v-else-if="proof.field==='metadata'" class="privacy-note">来源字段：{{proof.path.join(' → ')}}</p>
              <p v-else class="inline-error">这条依据与当前原文不一致。</p>
              <a v-if="safeSourceUrl(proof.source_url)" :href="safeSourceUrl(proof.source_url)??undefined" target="_blank" rel="noopener noreferrer" class="source-link">查看来源 ↗</a>
            </template>
            <p v-if="!selected.evidence.length" class="privacy-note">这是个人补充，没有自动提取的原文依据。</p>
          </template>
          <details class="feedback-entry">
            <summary>需要修正公共内容？</summary>
            <p class="privacy-note">仅在你主动提交后，后台才会收到问题。</p>
            <div class="item-actions">
              <button v-if="originalSelected" class="action-button" :disabled="saving" @click="openForm('item')">反馈当前条目</button>
              <button class="action-button" :disabled="saving" @click="openForm('missing')">反馈遗漏名称</button>
            </div>
          </details>
          <form v-if="form" ref="feedbackForm" class="edit-form" @submit.prevent="submit">
            <h4>{{form==='missing'?'申请识别遗漏名称':'反馈公共原始信息'}}</h4>
            <p v-if="form==='item'&&originalSelected&&base">反馈对象：{{itemName(originalSelected,base)}}</p>
            <p class="privacy-note">{{form==='missing'?'填写标题或摘要里实际出现的名称。':'反馈指向公共原始条目，不包含你的其他个人调整。'}}</p>
            <label v-if="form==='missing'">原文名称<input v-model="term" class="form-input" maxlength="200" required :disabled="saving"/></label>
            <label v-if="form==='item'">问题类型<select v-model="problemType" class="form-input" :disabled="saving"><option>信息不准确</option><option>名称不对</option><option>关联不合适</option><option>重复内容</option><option>其他问题</option></select></label>
            <label>补充说明（选填）<textarea v-model="message" maxlength="1700" rows="2" placeholder="不必重复填写论文名或条目，系统会附带对应信息和证据。" :disabled="saving"></textarea></label>
            <div class="item-actions">
              <button class="action-button primary-action" :disabled="saving||(form==='missing'&&!term.trim())">{{saving?'提交中…':'提交反馈'}}</button>
              <button type="button" class="action-button" :disabled="saving" @click="form=null">取消</button>
            </div>
          </form>
          <MyKnowledgeFeedback :paper-id="paperId" :refresh-version="feedbackVersion"/>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.knowledge-evidence{container-type:inline-size;margin:24px 0;min-width:0;color:#365660;font-size:15px;line-height:1.7}
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}
.section-heading h3{margin:0;font-size:20px;color:#284f58}
.section-heading p,.privacy-note{font-size:14px;color:#627c83;margin:8px 0;line-height:1.8}
.action-button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:9px 15px;border:1px solid #b7cfc8;border-radius:8px;background:#fff;color:#335e55;font:inherit;font-size:14px;line-height:1.5;cursor:pointer;gap:6px}
.action-button:hover:not(:disabled){background:#eaf5ef;border-color:#639d89}
.action-button:disabled{opacity:.45;cursor:default}
.primary-action{background:#e8f5ed;border-color:#7faf9b;font-weight:600}
.action-button:focus-visible,.knowledge-item:focus-visible,summary:focus-visible{outline:3px solid #73af9b;outline-offset:3px}
.adjustment-bar{position:sticky;top:8px;z-index:4;background:#f7fbf8;border:1px solid #c9ddd2;border-radius:10px;padding:12px;margin:18px 0;box-shadow:0 3px 12px #244c3410}
.bar-buttons,.item-actions,.collection-tabs{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.action-note{font-size:14px;color:#35694e;margin:10px 0 0}
.change-history{max-height:220px;overflow:auto;border-top:1px solid #dbe8df;margin-top:12px;padding-top:8px}
.change-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:10px 0}
.change-row span{overflow-wrap:anywhere;min-width:0}
.knowledge-workspace{display:grid;grid-template-columns:minmax(0,1fr);gap:18px;align-items:start}
.explorer{min-width:0}
.personal-graph,.item-browser,.proof-panel{border:1px solid #d5e3df;border-radius:10px;background:white;min-width:0}
.personal-graph{overflow:hidden;margin-bottom:16px}
.personal-graph h4{font-size:16px;padding:14px 16px;margin:0}
.personal-graph :deep(.graph-stage){height:380px;min-height:380px}
.personal-graph :deep(.cy-canvas){min-height:0;height:auto}
.personal-graph :deep(.graph-legend button){font-size:12px;min-height:30px}
.personal-graph :deep(.graph-controls .icon-button){width:36px;height:36px}
.personal-graph :deep(.graph-accessible){font-size:13px}
.personal-graph :deep(.graph-accessible .text-button){font-size:14px;padding:6px 0}
.collection-tabs{padding:12px;border-bottom:1px solid #e4ece8}
.item-list{max-height:300px;overflow:auto;padding:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px}
.knowledge-item{display:block;width:100%;text-align:left;border:1px solid #d5e3dd;background:white;border-radius:8px;padding:12px;overflow-wrap:anywhere;cursor:pointer}
.knowledge-item strong{display:block;font-size:15px;line-height:1.6}
.knowledge-item small{font-size:13px;color:#607d79}
.active{background:#e7f5ed;border-color:#71a68d}
.proof-panel{padding:20px;scroll-margin:150px 0 20px;outline:none}
.proof-panel:focus-visible{box-shadow:0 0 0 3px #9bc9b5}
.panel-label{font-size:13px;color:#607e78;margin:0 0 5px}
.proof-panel h4{font-size:20px;margin:0 0 14px;line-height:1.6;overflow-wrap:anywhere}
.proof-panel .item-actions{margin:12px 0}
.proof-panel label{display:block;margin:16px 0;font-size:14px;font-weight:500}
.proof-panel .form-input{font-size:15px;margin-top:6px}
blockquote{margin:16px 0;border-left:3px solid #69a38d;padding:12px;background:#f1f8f4;white-space:pre-wrap;overflow-wrap:anywhere;font-size:15px}
.source-text{max-height:300px;overflow:auto;font-size:15px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere}
mark{background:#ffdf79}
.source-link{display:inline-block;font-size:14px;padding:8px 0;color:#2d7461}
.edit-form{margin:16px 0;padding:16px;background:#f6faf8;border:1px solid #c9ded3;border-radius:8px;scroll-margin-top:150px}
.edit-form h4{font-size:17px}
textarea{display:block;width:100%;margin-top:8px;padding:10px;border:1px solid #bfd1c8;border-radius:6px;font:inherit}
.feedback-entry{margin-top:22px;padding-top:16px;border-top:1px solid #e0eae5}
summary{cursor:pointer;font-size:14px;padding:8px 0}
@container (min-width:850px){
  .knowledge-workspace{grid-template-columns:minmax(0,1.1fr) minmax(340px,.9fr)}
  .proof-panel{position:sticky;top:100px;max-height:calc(100vh - 125px);overflow:auto}
}
@container (max-width:480px){
  .section-heading{align-items:flex-start}
  .bar-buttons .action-button{flex:1 1 40%;padding:8px}
  .proof-panel{padding:15px;scroll-margin-top:210px}
  .personal-graph :deep(.graph-stage){height:320px;min-height:320px}
  .change-row{align-items:flex-start;flex-direction:column}
}
</style>
