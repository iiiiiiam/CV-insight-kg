<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,ref,watch} from 'vue'
import type {EntityDetail,Paper} from '../types.ts'
import {TYPE_LABELS} from '../types.ts'
import {research} from '../services/research.ts'
import AppIcon from './AppIcon.vue'
import StatePanel from './StatePanel.vue'

const props=defineProps<{id:string|null;type?:string}>()
const emit=defineEmits<{close:[];paper:[id:string]}>()
const loading=ref(false),error=ref(''),paper=ref<Paper|null>(null),entity=ref<EntityDetail|null>(null)
const panel=ref<HTMLElement|null>(null)
let generation=0,controller:AbortController|undefined,previous:HTMLElement|null=null
const title=computed(()=>paper.value?.title??entity.value?.node.label??'实体详情')
async function load(){
  const current=++generation;controller?.abort();paper.value=null;entity.value=null;error.value=''
  if(!props.id)return
  controller=new AbortController();loading.value=true
  try{
    if(props.type==='Paper'){
      const data=await research.getPaper(props.id,controller.signal);if(current===generation)paper.value=data
    }else{const data=await research.getEntity(props.id,controller.signal);if(current===generation)entity.value=data}
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
watch(()=>props.id,async(id,old)=>{
  if(id&&!old){previous=document.activeElement as HTMLElement;document.addEventListener('keydown',keydown);await nextTick();panel.value?.querySelector<HTMLButtonElement>('button')?.focus()}
  if(!id){document.removeEventListener('keydown',keydown);previous?.focus()}
  await load()
},{immediate:true})
onBeforeUnmount(()=>{controller?.abort();document.removeEventListener('keydown',keydown)})
</script>
<template>
  <Teleport to="body">
    <div v-if="id" class="drawer-overlay" @click.self="emit('close')">
      <aside ref="panel" class="detail-drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <header class="drawer-header"><span class="eyebrow">DETAIL & EVIDENCE</span><button class="icon-button" aria-label="关闭详情" @click="emit('close')"><AppIcon name="close"/></button></header>
        <StatePanel v-if="loading" kind="loading" title="正在读取详情"/>
        <StatePanel v-else-if="error" kind="error" title="详情加载失败" :description="error" retry @retry="load"/>
        <template v-else>
          <span class="badge badge-teal">{{paper?'论文':entity?TYPE_LABELS[entity.node.type]:'详情'}}</span>
          <h2 id="drawer-title">{{title}}</h2>
          <template v-if="paper">
            <p class="detail-meta">{{paper.year}} · {{paper.venue}}</p>
            <p class="author-line">{{paper.authors.join(' / ')}}</p>
            <h3>记录概述</h3><p class="body-copy">{{paper.abstract}}</p>
            <h3>知识标注状态</h3>
            <dl class="definition-list"><dt>主题</dt><dd>{{paper.topic}}</dd><dt>方法</dt><dd>{{paper.method}}</dd><dt>任务</dt><dd>{{paper.task}}</dd><dt>数据集</dt><dd>{{paper.dataset}}</dd><dt>机构</dt><dd>{{paper.institution}}</dd></dl>
            <h3>来源与证据</h3>
            <p class="evidence-copy">{{paper.evidence}}</p>
            <dl class="definition-list"><dt>来源</dt><dd>{{paper.source}}</dd><dt>A 记录 ID</dt><dd class="mono">{{paper.id}}</dd><dt>OpenAlex ID</dt><dd class="mono">{{paper.openalex_id||'未提供'}}</dd><dt>DOI</dt><dd class="mono">{{paper.doi||'未提供'}}</dd><dt>去重键</dt><dd class="mono">{{paper.canonical_key||'未提供'}}</dd><dt>导入批次 ID</dt><dd class="mono">{{paper.batch_ids?.length?paper.batch_ids.join(', '):paper.batch_id}}</dd></dl>
            <div v-for="source in paper.sources" :key="source.name+source.source_id" class="source-record"><strong>{{source.name}}</strong><p class="small-note">{{source.source_id}} · 采集时间 {{source.retrieved_at}}</p><a v-if="source.url" :href="source.url" target="_blank" rel="noopener noreferrer" class="text-button">查看来源记录<AppIcon name="external" :size="15"/></a></div>
            <a v-if="paper.source_url" :href="paper.source_url" target="_blank" rel="noopener noreferrer" class="text-button">查看原始来源<AppIcon name="external" :size="15"/></a>
            <p v-else class="small-note">A 接口未返回可访问的来源链接。</p>
            <RouterLink v-if="paper.openalex_id" :to="{path:'/admin/reviews',query:{paper_id:paper.openalex_id}}" class="related-paper">查看 B 待审核候选及原文证据（需管理员登录）</RouterLink>
          </template>
          <template v-else-if="entity">
            <p class="body-copy">A 当前数据库中，该会议共 {{entity.total??entity.papers.length}} 篇论文，当前显示 {{entity.papers.length}} 篇。依据 venue 元数据，不受研究列表当前筛选限制。</p>
            <h3>关联论文</h3>
            <button v-for="p in entity.papers" :key="p.id" class="related-paper" @click="emit('paper',p.id)"><span>{{p.title}}</span><small>{{p.year}} · {{p.method}}</small><AppIcon name="arrow"/></button>
            <p v-if="!entity.papers.length" class="small-note">当前样本中没有关联论文。</p>
            <dl class="definition-list"><dt>实体 ID</dt><dd class="mono">{{entity.node.id}}</dd><dt>数据范围</dt><dd>{{entity.batch_id}}</dd></dl>
          </template>
        </template>
      </aside>
    </div>
  </Teleport>
</template>
