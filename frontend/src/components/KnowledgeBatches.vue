<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {auth} from '../stores/auth.ts'
import {getKnowledgeBatches,importKnowledgeBatch,withdrawKnowledgeBatch,enrichKnowledgeBatches} from '../services/knowledge-batches.ts'
import type {BatchStatus,BatchReceipt} from '../services/knowledge-batches.ts'

const emit=defineEmits<{changed:[];'busy-change':[busy:boolean]}>()
const state=ref<BatchStatus|null>(null),busy=ref(false),error=ref(''),notice=ref('')
const document=ref<Record<string,unknown>|null>(null),filename=ref(''),acknowledged=ref(false),pending=ref('')
const receipt=ref<BatchReceipt|null>(null)
watch(busy,value=>emit('busy-change',value),{flush:'sync'})
let poll:ReturnType<typeof setTimeout>|undefined,closed=false
onUnmounted(()=>{closed=true;clearTimeout(poll);emit('busy-change',false)})
async function refresh(quiet=false){
  if(!quiet)busy.value=true
  error.value=''
  try{state.value=await getKnowledgeBatches()}
  catch(e){state.value=null;error.value=e instanceof Error?e.message:'批次读取失败'}
  finally{
    if(!quiet)busy.value=false
    clearTimeout(poll)
    if(!closed&&state.value?.source_enrichment.running)poll=setTimeout(()=>refresh(true),3000)
  }
}
async function enrich(){
  if(busy.value)return
  busy.value=true;error.value=''
  try{await enrichKnowledgeBatches(auth.session?.csrf_token??'');notice.value='已开始补充来源，可继续浏览；完成后刷新知识页面查看。';await refresh()}
  catch(e){error.value=e instanceof Error?e.message:'来源补充启动失败'}
  finally{busy.value=false}
}
async function choose(event:Event){
  document.value=null;filename.value='';acknowledged.value=false;error.value='';receipt.value=null;notice.value=''
  const file=(event.target as HTMLInputElement).files?.[0]
  if(!file)return
  try{
    if(file.size>10*1024*1024)throw new Error('请选择不超过 10 MB 的批次文件。')
    const value:unknown=JSON.parse(await file.text())
    if(!value||typeof value!=='object'||Array.isArray(value)||!('format_version' in value)||value.format_version!=='a-paperinput/1')throw new Error('请选择 A 导出的 a-paperinput/1 批次 JSON，不是 effective.json。')
    document.value=value as Record<string,unknown>;filename.value=file.name
  }catch(e){error.value=e instanceof Error?e.message:'文件无法读取'}
}
async function apply(code?:string){
  if(!state.value||busy.value||(!code&&(!document.value||!acknowledged.value)))return
  busy.value=true;error.value='';notice.value='';receipt.value=null
  try{
    const token=auth.session?.csrf_token??''
    receipt.value=code?await withdrawKnowledgeBatch(code,state.value.revision,token):await importKnowledgeBatch(document.value!,state.value.revision,token)
    pending.value=''
    notice.value=receipt.value.status==='failed'?'本次导入未生效，当前知识保持不变。修正文件后可以重试。':receipt.value.status==='unchanged'?'没有重复处理，当前结果保持不变。':receipt.value.status==='withdrawn'?(code?'批次已撤回，B 当前知识已更新。':'该批次已撤回，重复导入不会重新启用，请使用新批次。'):'导入完成，B 当前知识已更新。'
    acknowledged.value=false
    emit('changed')
    await refresh()
  }catch(e){error.value=e instanceof Error?e.message:'操作失败，请刷新后核对'}
  finally{busy.value=false}
}
onMounted(()=>refresh())
</script>

<template>
  <section class="batch-section" aria-label="论文批次管理">
    <div class="batch-heading"><div><h2>论文批次</h2><p>导入数据采集模块交接的论文，在这里统一管理新增、更新和撤回。</p></div><button class="button button-secondary" :disabled="busy" @click="refresh()">刷新批次</button></div>
    <p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <p v-if="notice" role="status">{{notice}}</p>
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <template v-if="state">
      <p class="batch-note">{{state.managed?`当前使用批次管理中的 ${state.paper_count} 篇论文。`:'当前仍使用原有论文数据，尚未切换到批次管理。'}} 导入和撤回会影响 B 知识页面及有效结果导出；正式图谱是否更新，请在发布模块核对。</p>
      <section class="panel batch-card"><h3>导入批次</h3>
        <p>选择 A 导出的批次 JSON 文件。同一论文只保留一份，后接收的内容更新优先。</p>
        <label>批次文件<input type="file" accept=".json,application/json" :disabled="busy" @change="choose"/></label>
        <p v-if="document">{{filename}} · 批次 {{document.batch_code}} · 待接收 {{document.exported_papers}} 篇</p>
        <p v-if="!state.managed" class="batch-note">首次成功导入后，将以批次中的论文作为当前输入，原有 150 篇不会自动合并。原始样本文件和旧反馈存档保留；批次模式使用独立的反馈存档。</p>
        <details><summary>识别范围说明</summary><p>与原有样本共用来源增强、词表和原文规则。导入后自动在后台补充 OpenAlex 和外部论文目录的信息；已有信息直接复用，未收录或暂时不可用时仍保留规则识别结果。补充完成后请刷新知识页面，并重新导出最新结果。</p></details>
        <label class="check"><input v-model="acknowledged" type="checkbox" :disabled="busy||!document"/>我已确认本次导入将更新 B 当前论文范围和知识结果。</label>
        <button class="button button-primary" :disabled="busy||!document||!acknowledged" @click="apply()">导入并更新 B</button>
      </section>
      <section v-if="state.managed" class="panel batch-card"><h3>来源补充</h3>
        <p>{{state.source_enrichment.running?'正在后台补充来源，可继续浏览。':'当前补充进度'}} 已处理 {{state.source_enrichment.completed}} / {{state.source_enrichment.total}} 篇，其中 {{state.source_enrichment.with_sources}} 篇有外部补充信息。</p>
        <p v-if="state.source_enrichment.partial">{{state.source_enrichment.partial}} 篇尚未取得全部来源，可能未被目录收录或来源暂不可用；现有规则识别结果仍可使用。</p>
        <p v-if="state.source_enrichment.error" class="inline-error">{{state.source_enrichment.error}}</p>
        <button class="button button-secondary" :disabled="busy||state.source_enrichment.running||!state.paper_count" @click="enrich">补充未取得的来源</button>
        <p>只补充缺少的信息，不重复请求已取得的来源。完成后刷新知识页面或重新导出；“已处理”不代表每篇都取得了全部来源。</p>
      </section>
      <div v-if="receipt" class="batch-note" role="status">
        <template v-if="receipt.accepted!==undefined">接收 {{receipt.accepted}} 篇；新增 {{receipt.new??0}}，更新 {{receipt.updated??0}}，重复 {{receipt.duplicates??0}}。</template>
        <template v-if="receipt.removed!==undefined">移出当前范围 {{receipt.removed}} 篇；由其他批次保留 {{receipt.retained}} 篇，其中恢复旧内容 {{receipt.restored}} 篇。</template>
        <p v-if="receipt.failed">错误 {{receipt.failed}} 项，整批未生效。</p>
        <ul v-if="receipt.errors?.length"><li v-for="(item,index) in receipt.errors" :key="index">{{item.index===null?'文件结构':`第 ${item.index+1} 条论文`}}：{{item.reason}}</li></ul>
      </div>
      <section class="panel batch-card"><h3>已接收批次（{{state.batches.length}}）</h3><p v-if="!state.batches.length">暂无已接收批次。</p>
        <article v-for="batch in state.batches" :key="batch.batch_code" class="batch-row">
          <div><strong>{{batch.batch_code}}</strong><span> · {{batch.active?'生效中':'已撤回'}} · {{batch.paper_count}} 篇</span><p>首次接收：新增 {{batch.receipt.new}}，更新 {{batch.receipt.updated}}，重复 {{batch.receipt.duplicates}}。</p></div>
          <button v-if="batch.active&&pending!==batch.batch_code" class="button button-secondary" :disabled="busy" @click="pending=batch.batch_code">撤回批次</button>
          <div v-if="pending===batch.batch_code" class="batch-confirm"><p>确认撤回 {{batch.batch_code}}？仅由该批次提供的论文将移出；其他批次仍提供的论文会保留，必要时恢复先前内容。撤回全部批次后，当前论文列表为空。</p><button class="button button-secondary" :disabled="busy" @click="pending=''">取消</button> <button class="button button-primary" :disabled="busy" @click="apply(batch.batch_code)">确认撤回</button></div>
        </article>
      </section>
      <details v-if="state.failures.length" class="panel batch-card"><summary>最近未成功的导入（{{state.failures.length}}）</summary><article v-for="(failure,index) in state.failures" :key="index"><p>{{failure.batch_code??'无批次号'}} · {{failure.occurred_at}}</p><ul><li v-for="(item,i) in failure.result.errors" :key="i">{{item.index===null?'文件结构':`第 ${item.index+1} 条论文`}}：{{item.reason}}</li></ul></article></details>
    </template>
  </section>
</template>

<style scoped>
.batch-section{margin-top:20px}.batch-heading{display:flex;align-items:start;justify-content:space-between;gap:16px}.batch-section p{line-height:1.8;overflow-wrap:anywhere}.batch-card{padding:20px;margin:18px 0}.batch-note,.batch-confirm{padding:14px;background:#f1f7f4;border:1px solid #d8e9e2;border-radius:8px;margin:14px 0;line-height:1.8}.batch-card label{display:block;margin:16px 0}.batch-card input[type=file]{display:block;margin-top:10px;max-width:100%}.check{display:flex!important;align-items:start;gap:8px}.check input{margin-top:6px}.batch-row{display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;padding:18px 0;border-top:1px solid #d8e9e2}.batch-row p{margin:8px 0}.batch-confirm{flex-basis:100%}.batch-card li{overflow-wrap:anywhere}.batch-card summary{cursor:pointer}.batch-section .button{min-height:44px}
</style>
