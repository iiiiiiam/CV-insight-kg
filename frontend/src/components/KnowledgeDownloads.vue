<script setup lang="ts">
import {ref} from 'vue'
import {fetchKnowledgeDownload} from '../services/knowledge.ts'
import type {ExportFormat} from '../services/knowledge.ts'
const props=defineProps<{revision:string;disabled?:boolean}>()
const busy=ref(false),error=ref(''),notice=ref('')
const formats:Array<{format:ExportFormat;label:string}>=[
  {format:'confirmed.json',label:'已确认 JSON'},{format:'pending.json',label:'待审核 JSON'},
  {format:'rejected.json',label:'已驳回 JSON'},{format:'bundle.zip',label:'完整 ZIP'},
]
async function download(format:ExportFormat){
  busy.value=true;error.value='';notice.value=''
  try{
    const blob=await fetchKnowledgeDownload(format,props.revision)
    const url=URL.createObjectURL(blob),anchor=document.createElement('a')
    anchor.href=url;anchor.download=format==='bundle.zip'?'b-knowledge.zip':`b-${format}`
    document.body.appendChild(anchor);anchor.click();anchor.remove()
    setTimeout(()=>URL.revokeObjectURL(url),1000)
    notice.value='文件已生成并交给浏览器下载。'
  }catch(e){error.value=e instanceof Error?e.message:'下载失败，请重新读取存档后重试。'}
  finally{busy.value=false}
}
</script>
<template><section class="panel download-card"><h2>B 业务结果下载</h2><p>导出范围是当前固定样本全部论文，与页面所选论文及筛选条件无关。三种状态分开，完整 ZIP 另含 Schema 与校验清单。</p><div class="download-buttons"><button v-for="item in formats" :key="item.format" class="button button-secondary" :disabled="busy||disabled" @click="download(item.format)">{{item.label}}</button></div><p v-if="busy" role="status">正在校验并生成文件…</p><p v-if="notice" role="status">{{notice}}</p><p v-if="error" class="inline-error" role="alert">{{error}}</p></section></template>
<style scoped>.download-card{padding:24px;margin:20px 0}.download-card p{font-size:12px;line-height:1.8;color:#718995;margin-top:12px}.download-buttons{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}.download-card p.inline-error{color:#a35d50}</style>
