<script setup lang="ts">
import AppIcon from './AppIcon.vue'
defineProps<{kind:'loading'|'empty'|'error';title:string;description?:string;retry?:boolean}>()
defineEmits<{retry:[]}>()
</script>
<template>
  <div class="state-panel" :class="kind" :role="kind==='error'?'alert':'status'">
    <span v-if="kind==='loading'" class="spinner" aria-hidden="true"></span>
    <span v-else class="state-symbol"><AppIcon :name="kind==='empty'?'search':'info'" :size="25"/></span>
    <strong>{{title}}</strong><p v-if="description">{{description}}</p>
    <button v-if="retry" class="button button-secondary" @click="$emit('retry')"><AppIcon name="refresh"/>重新加载</button>
  </div>
</template>
