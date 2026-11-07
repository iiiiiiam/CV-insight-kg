<script setup lang="ts">
import {computed,ref} from 'vue'
import type {GraphData,Paper} from '../types.ts'

const props=defineProps<{papers:Paper[];graph:GraphData;raw:boolean;activeYear:string;activeTopic:string;activeMethod:string}>()
const emit=defineEmits<{filter:[key:'year'|'topic'|'method',value:string]}>()
const dimension=ref<'topic'|'method'>('topic')
interface BarItem {key:string;label:string;value:number}
function ranked(values:string[],limit=8):BarItem[]{
  const counts=new Map<string,number>()
  for(const value of values.map(v=>v.trim()).filter(Boolean))counts.set(value,(counts.get(value)??0)+1)
  return [...counts].map(([label,value])=>({key:label,label,value})).sort((a,b)=>b.value-a.value||a.label.localeCompare(b.label,'zh-CN')).slice(0,limit)
}
const years=computed(()=>ranked(props.papers.filter(p=>p.year>0).map(p=>String(p.year)),10).sort((a,b)=>Number(a.key)-Number(b.key)))
const knowledge=computed(()=>{
  if(props.raw)return ranked(props.papers.map(p=>p.venue).filter(v=>v&&v!=='—'))
  const kind=dimension.value==='topic'?'Topic':'Method'
  return ranked(props.graph.nodes.filter(n=>n.type===kind).map(n=>n.label))
})
const maxYear=computed(()=>Math.max(1,...years.value.map(x=>x.value)))
const maxKnowledge=computed(()=>Math.max(1,...knowledge.value.map(x=>x.value)))
function active(item:BarItem){
  if(props.raw)return false
  return dimension.value==='topic'?props.activeTopic===item.key:props.activeMethod===item.key
}
function chooseKnowledge(item:BarItem){if(!props.raw)emit('filter',dimension.value,item.key)}
</script>

<template><section class="visual-overview" aria-labelledby="visual-overview-title">
  <header><div><div class="eyebrow">VISUAL RESEARCH OVERVIEW</div><h2 id="visual-overview-title">研究分布概览</h2><p>统计范围为当前页面已读取的数据，不外推为整个研究领域。</p></div><span class="scope-badge">{{papers.length}} 篇可见论文</span></header>
  <div class="chart-grid">
    <article class="chart-card"><div class="chart-title"><div><h3>年份分布</h3><small>点击年份即可筛选论文列表</small></div><button v-if="activeYear" class="text-button" @click="emit('filter','year','')">清除年份</button></div>
      <div v-if="years.length" class="year-chart">
        <button v-for="item in years" :key="item.key" :class="{active:activeYear===item.key}" :aria-label="`${item.key} 年，${item.value} 篇`" @click="emit('filter','year',activeYear===item.key?'':item.key)">
          <span class="bar-value">{{item.value}}</span><i :style="{height:`${Math.max(12,item.value/maxYear*100)}%`}"></i><span>{{item.label}}</span>
        </button>
      </div><p v-else class="chart-empty">当前范围没有可统计的年份。</p>
    </article>
    <article class="chart-card"><div class="chart-title"><div><h3>{{raw?'会议分布':'当前子图的主题 / 方法'}}</h3><small>{{raw?'来自 A 的论文元数据':'点击条目可筛选同批论文；计数仅代表当前展开子图'}}</small></div><div v-if="!raw" class="dimension-switch"><button :class="{active:dimension==='topic'}" @click="dimension='topic'">主题</button><button :class="{active:dimension==='method'}" @click="dimension='method'">方法</button></div></div>
      <div v-if="knowledge.length" class="rank-chart"><button v-for="item in knowledge" :key="item.key" :disabled="raw" :class="{active:active(item)}" @click="chooseKnowledge(item)"><span :title="item.label">{{item.label}}</span><i><b :style="{width:`${Math.max(5,item.value/maxKnowledge*100)}%`}"></b></i><strong>{{item.value}}</strong></button></div>
      <p v-else class="chart-empty">{{raw?'当前范围没有会议数据。':'请先选择论文并展开图谱；C 返回主题或方法节点后会显示在这里。'}}</p>
    </article>
  </div>
</section></template>

<style scoped>
.visual-overview{margin:0 0 20px}.visual-overview>header{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:12px}.visual-overview h2{color:#355866}.visual-overview header p{font-size:10px;color:#92a3ab;margin-top:5px}.scope-badge{font-size:10px;color:#4c8278;background:#eaf5f1;border:1px solid #d8ebe5;border-radius:999px;padding:6px 10px;white-space:nowrap}.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.chart-card{background:#fff;border:1px solid #e3ecef;border-radius:12px;padding:17px 18px;min-height:226px}.chart-title{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.chart-title h3{font-size:13px;color:#496874}.chart-title small{display:block;font-size:9px;color:#9aabb3;margin-top:5px}.year-chart{height:145px;display:flex;align-items:end;gap:7px;padding-top:27px}.year-chart button{height:100%;min-width:26px;flex:1;border:0;background:transparent;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:5px;color:#879ba5;font-size:9px;padding:0}.year-chart button i{display:block;width:min(24px,75%);background:linear-gradient(#73b9aa,#31927f);border-radius:5px 5px 2px 2px;min-height:12px;transition:height .18s,filter .18s}.year-chart button:hover i,.year-chart button.active i{filter:saturate(1.5);box-shadow:0 0 0 3px #dff2ec}.year-chart button.active{color:#167a6c;font-weight:700}.bar-value{font-size:8px;color:#6e8791}.dimension-switch{display:flex;background:#f0f5f6;border-radius:6px;padding:2px}.dimension-switch button{border:0;background:transparent;color:#879ca5;border-radius:4px;padding:4px 8px;font-size:9px}.dimension-switch button.active{background:#fff;color:#197b6d;box-shadow:0 1px 4px #294b5615}.rank-chart{display:flex;flex-direction:column;gap:11px;margin-top:19px}.rank-chart button{display:grid;grid-template-columns:minmax(72px,1fr) 2fr 24px;gap:10px;align-items:center;border:0;background:transparent;padding:0;text-align:left;color:#68818c;font-size:10px}.rank-chart button>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.rank-chart button>i{height:7px;background:#edf3f4;border-radius:9px;overflow:hidden}.rank-chart button b{display:block;height:100%;background:#77b7aa;border-radius:9px}.rank-chart button strong{text-align:right;font-size:9px;font-weight:600}.rank-chart button:not(:disabled):hover,.rank-chart button.active{color:#147d6e}.rank-chart button.active b{background:#168c79}.chart-empty{height:145px;display:grid;place-items:center;text-align:center;color:#9cadb4;font-size:10px;line-height:1.8;padding:20px}.rank-chart button:disabled{opacity:1;cursor:default}@media(max-width:960px){.chart-grid{grid-template-columns:1fr}}@media(max-width:700px){.visual-overview>header{align-items:flex-start}.chart-card{padding:15px 13px}.year-chart{gap:3px}.year-chart button{font-size:8px}.chart-title{flex-wrap:wrap}}
</style>
