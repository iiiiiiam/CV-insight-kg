<script setup lang="ts">
import {computed} from 'vue'

interface DistributionItem {id:string;name:string;paper_count:number}
const props=defineProps<{title:string;items:DistributionItem[];paperTotal:number;emptyText?:string}>()
const emit=defineEmits<{select:[id:string]}>()
const colors=['#2f8b7c','#527eb5','#b67b3c','#9b6a9c','#6f8b48','#b65f72','#5f8f9f','#a38345']
const visible=computed(()=>props.items.slice(0,8))
const hitTotal=computed(()=>visible.value.reduce((sum,item)=>sum+item.paper_count,0))
const segments=computed(()=>{
  let start=0
  return visible.value.map((item,index)=>{
    const size=hitTotal.value?item.paper_count/hitTotal.value*100:0
    const segment={...item,color:colors[index%colors.length]!,start,end:start+size}
    start+=size
    return segment
  })
})
const chartStyle=computed(()=>({
  background:hitTotal.value
    ? `conic-gradient(${segments.value.map(item=>`${item.color} ${item.start}% ${item.end}%`).join(',')})`
    : '#e9f1ef',
}))
function paperShare(count:number){return props.paperTotal?`${(count/props.paperTotal*100).toFixed(1)}%`: '0.0%'}
</script>

<template>
  <section class="panel donut-card">
    <h2>{{title}}</h2>
    <p v-if="!visible.length" class="small-note">{{emptyText??'当前批次没有可统计的数据。'}}</p>
    <template v-else>
      <div class="donut-layout">
        <div class="donut" :style="chartStyle" role="img" :aria-label="`${title}，共${visible.length}项`">
          <div><strong>{{visible.length}}</strong><span>项</span></div>
        </div>
        <div class="legend">
          <button v-for="item in segments" :key="item.id" type="button" @click="emit('select',item.id)">
            <i :style="{background:item.color}"></i><span :title="item.name">{{item.name}}</span>
            <b>{{item.paper_count}}篇</b><small>{{paperShare(item.paper_count)}}</small>
          </button>
        </div>
      </div>
      <p class="chart-note">百分比表示该标签覆盖的机构论文比例；同篇论文可属于多个标签，因此各项之和可能超过 100%。圆环按当前展示标签的关联次数绘制。</p>
    </template>
  </section>
</template>

<style scoped>
.donut-card{padding:18px 20px;min-width:0}.donut-card h2{font-size:16px;margin-bottom:12px}
.donut-layout{display:grid;grid-template-columns:150px minmax(0,1fr);align-items:center;gap:18px}
.donut{width:142px;aspect-ratio:1;border-radius:50%;display:grid;place-items:center;box-shadow:inset 0 0 0 1px rgba(39,76,79,.06)}
.donut>div{width:76px;aspect-ratio:1;border-radius:50%;background:#fbfdfd;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#557177;box-shadow:0 0 0 1px rgba(39,76,79,.08)}
.donut strong{font-size:25px;color:#245f59}.donut span{font-size:11px}
.legend{display:grid;gap:4px;min-width:0}.legend button{display:grid;grid-template-columns:9px minmax(0,1fr) max-content 43px;align-items:center;gap:7px;border:0;background:transparent;text-align:left;padding:5px;border-radius:5px;color:#35565f;cursor:pointer;font:inherit}
.legend button:hover,.legend button:focus-visible{background:#edf7f3}.legend i{width:9px;height:9px;border-radius:50%}.legend span{font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.legend b{font-size:11px}.legend small{font-size:10px;color:#71878e;text-align:right}
.chart-note{font-size:11px;color:#6c8289;line-height:1.65;margin-top:12px}
@media(max-width:560px){.donut-layout{grid-template-columns:1fr}.donut{margin:auto}.legend button{grid-template-columns:9px minmax(0,1fr) max-content 40px}}
</style>
