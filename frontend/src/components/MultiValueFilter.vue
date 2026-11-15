<script setup lang="ts">
import {ref,watch} from 'vue'

const props=defineProps<{label:string;modelValue:string[];placeholder?:string}>()
const emit=defineEmits<{"update:modelValue":[value:string[]]}>()
const draft=ref('')

function add(){
  const value=draft.value.trim()
  if(!value)return
  if(!props.modelValue.some(item=>item.toLocaleLowerCase()===value.toLocaleLowerCase())){
    emit('update:modelValue',[...props.modelValue,value])
  }
  draft.value=''
}
function remove(index:number){emit('update:modelValue',props.modelValue.filter((_,i)=>i!==index))}
function keydown(event:KeyboardEvent){
  if(event.key==='Enter'||event.key===';'){
    event.preventDefault()
    add()
  }
}
watch(()=>props.modelValue,()=>{if(!props.modelValue.length)draft.value=''})
</script>

<template>
  <fieldset class="multi-filter">
    <legend>{{label}}</legend>
    <div class="entry-row">
      <input v-model="draft" class="form-input" maxlength="500" :placeholder="placeholder??'输入名称或图谱 ID'"
        @keydown="keydown" @blur="add"/>
      <button type="button" class="button button-secondary" :disabled="!draft.trim()" @mousedown.prevent @click="add">添加</button>
    </div>
    <div v-if="modelValue.length" class="chips" :aria-label="`${label}已选条件`">
      <span v-for="(value,index) in modelValue" :key="value" class="filter-chip">{{value}}
        <button type="button" :aria-label="`移除${value}`" @click="remove(index)">×</button>
      </span>
    </div>
    <small>同一栏多个值取并集；不同栏之间取交集。</small>
  </fieldset>
</template>

<style scoped>
.multi-filter{min-width:0;margin:0;padding:0;border:0}.multi-filter legend{font-size:13px;margin-bottom:5px}
.entry-row{display:flex;gap:7px}.entry-row .form-input{min-width:0}.entry-row .button{padding:8px 12px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.filter-chip{display:inline-flex;align-items:center;gap:5px;max-width:100%;padding:4px 8px;border-radius:999px;background:#e9f4f0;color:#246b60;font-size:12px;overflow-wrap:anywhere}
.filter-chip button{border:0;background:transparent;color:inherit;font-size:17px;line-height:1;cursor:pointer}.multi-filter small{display:block;margin-top:6px;color:#78909a;font-size:11px;line-height:1.5}
</style>
