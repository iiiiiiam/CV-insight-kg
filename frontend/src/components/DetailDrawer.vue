<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,ref,watch} from 'vue'
import type {CDetail,EntityDetail,Paper} from '../types.ts'
import {TYPE_LABELS} from '../types.ts'
import {rawResearch} from '../services/research.ts'
import {graphResearch} from '../services/graph.ts'
import CGraphDetail from './CGraphDetail.vue'
import AppIcon from './AppIcon.vue'
import StatePanel from './StatePanel.vue'
import KnowledgeEvidence from './KnowledgeEvidence.vue'

const props=defineProps<{id:string|null;type?:string;source?:'a'|'c';batchId?:string}>()
const emit=defineEmits<{close:[];paper:[id:string];navigate:[id:string,type:string];explore:[id:string]}>()
const loading=ref(false),error=ref(''),paper=ref<Paper|null>(null),entity=ref<EntityDetail|null>(null)
const panel=ref<HTMLElement|null>(null)
const cDetail=ref<CDetail|null>(null)
let generation=0,controller:AbortController|undefined,previous:HTMLElement|null=null
const title=computed(()=>cDetail.value?.node.name??paper.value?.title??entity.value?.node.label??'实体详情')
async function load(){
  const current=++generation;controller?.abort();paper.value=null;entity.value=null;cDetail.value=null;error.value=''
  if(!props.id)return
  controller=new AbortController();loading.value=true
  try{
    if((props.source??(/^\d+$/.test(props.id)?'a':'c'))==='c'){
      const data=await graphResearch.getDetail(props.id,controller.signal,props.batchId);if(current===generation)cDetail.value=data
    }else if(props.type==='Paper'){
      const data=await rawResearch.getPaper(props.id,controller.signal);if(current===generation)paper.value=data
    }else{const data=await rawResearch.getEntity(props.id,controller.signal);if(current===generation)entity.value=data}
  }catch(e){if(current===generation&&!(e instanceof DOMException&&e.name==='AbortError'))error.value=e instanceof Error?e.message:'加载失败'}
  finally{if(current===generation)loading.value=false}
}
function keydown(event:KeyboardEvent){
  if(!props.id)return
  if(event.key==='Escape'){emit('close');return}
  if(event.key==='Tab'&&panel.value){
    const items=[...panel.value.querySelectorAll<HTMLElement>('button,a[href],input,select,[tabindex="0"]')].filter(el=>!el.hasAttribute('disabled'))
    const first=items[0],last=items[items.length-1]
    if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}
  }
}
watch(()=>[props.id,props.batchId,props.source] as const,async(value,previousValue)=>{
  const id=value[0],old=previousValue?.[0]
  if(id&&!old){previous=document.activeElement as HTMLElement;document.addEventListener('keydown',keydown);await nextTick();panel.value?.querySelector<HTMLButtonElement>('button')?.focus()}
  if(!id){document.removeEventListener('keydown',keydown);previous?.focus()}
  await load()
},{immediate:true})
onBeforeUnmount(()=>{controller?.abort();document.removeEventListener('keydown',keydown)})
</script>
<template>
  <Teleport to="body">
    <div v-if="id" class="drawer-overlay" @click.self="emit('close')">
      <aside ref="panel" class="detail-drawer" role="dialog" aria-modal="true" :aria-label="title">
        <header class="drawer-header"><span class="eyebrow">DETAIL & EVIDENCE</span><button class="icon-button" aria-label="关闭详情" @click="emit('close')"><AppIcon name="close"/></button></header>
        <StatePanel v-if="loading" kind="loading" title="正在读取详情"/>
        <StatePanel v-else-if="error" kind="error" title="详情加载失败" :description="error" retry @retry="load"/>
        <template v-else-if="cDetail"><span class="badge badge-teal">C 已审核发布批次 · {{cDetail.batch_id}}</span><CGraphDetail :detail="cDetail" @navigate="id=>emit('navigate',id,cDetail?.related.find(n=>n.id===id)?.type??'Paper')"/><button class="button button-secondary" @click="emit('explore',cDetail.node.id)">以此节点展开图谱</button></template>
        <template v-else>
          <span class="badge badge-teal">{{paper?'论文':entity?TYPE_LABELS[entity.node.type]:'详情'}}</span>
          <h2 id="drawer-title">{{title}}</h2>
          <template v-if="paper">
            <p class="detail-meta">{{paper.year}} · {{paper.venue}}</p>
            <p class="author-line">{{paper.authors.join(' / ')}}</p>
            <h3>记录概述</h3><p class="body-copy">{{paper.abstract}}</p>
            <KnowledgeEvidence v-if="paper.openalex_id" :paper-id="paper.openalex_id"/>
            <p v-else class="small-note">来源记录未提供 OpenAlex ID，暂无法关联知识与证据。</p>
            <h3>来源与证据</h3>
            <p class="evidence-copy">{{paper.evidence}}</p>
            <dl class="definition-list"><dt>来源</dt><dd>{{paper.source}}</dd><dt>A 记录 ID</dt><dd class="mono">{{paper.id}}</dd><dt>OpenAlex ID</dt><dd class="mono">{{paper.openalex_id||'未提供'}}</dd><dt>DOI</dt><dd class="mono">{{paper.doi||'未提供'}}</dd><dt>去重键</dt><dd class="mono">{{paper.canonical_key||'未提供'}}</dd><dt>导入批次 ID</dt><dd class="mono">{{paper.batch_ids?.length?paper.batch_ids.join(', '):paper.batch_id}}</dd></dl>
            <div v-for="source in paper.sources" :key="source.name+source.source_id" class="source-record"><strong>{{source.name}}</strong><p class="small-note">{{source.source_id}} · 采集时间 {{source.retrieved_at}}</p><a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" class="text-button">查看来源记录<AppIcon name="external" :size="15"/></a></div>
            <a v-if="paper.source_url" :href="paper.source_url" target="_blank" rel="noopener noreferrer" class="text-button">查看原始来源<AppIcon name="external" :size="15"/></a>
            <p v-else class="small-note">A 接口未返回可访问的来源链接。</p>
            <RouterLink v-if="paper.openalex_id" :to="{path:'/research/knowledge',query:{paper_id:paper.openalex_id}}" class="related-paper">查看该论文的知识与证据</RouterLink>
          </template>
          <template v-else-if="entity">
            <p class="body-copy">A 当前数据库中，该会议共 {{entity.total??entity.papers.length}} 篇论文，当前显示 {{entity.papers.length}} 篇。依据 venue 元数据，不受研究列表当前筛选限制。</p>
            <h3>关联论文</h3>
            <button v-for="p in entity.papers" :key="p.id" class="related-paper" @click="emit('paper',p.id)"><span>{{p.title}}</span><small>{{p.year}} · {{p.venue}}</small><AppIcon name="arrow"/></button>
            <p v-if="!entity.papers.length" class="small-note">当前样本中没有关联论文。</p>
            <dl class="definition-list"><dt>实体 ID</dt><dd class="mono">{{entity.node.id}}</dd><dt>数据范围</dt><dd>{{entity.batch_id}}</dd></dl>
          </template>
        </template>
      </aside>
    </div>
  </Teleport>
</template>
