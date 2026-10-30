<script setup lang="ts">
import {computed} from 'vue'
import {useRoute} from 'vue-router'
import {MENU} from '../navigation.ts'
import AppIcon from '../components/AppIcon.vue'
const route=useRoute()
const item=computed(()=>MENU.find(n=>n.id===route.meta.navId))
</script>
<template>
  <section class="standard-page placeholder-page">
    <div class="page-heading"><div><div class="eyebrow">{{item?.id??'NOT FOUND'}}</div><h1>{{route.meta.title}}</h1><p>{{item?`${item.group} / ${item.section}`:'请检查地址，或返回研究工作台。'}}</p></div></div>
    <div class="panel placeholder-card"><span class="placeholder-symbol"><AppIcon :name="item?'layers':'search'" :size="36"/></span><span class="badge badge-outline">{{item?'路由已就绪 · 功能待实现':'404'}}</span><h2>{{item?'这个功能尚未接入':'没有找到这个页面'}}</h2><p v-if="item">当前已保留菜单和页面入口，业务实现由 {{item.owner}} 负责。</p><p v-if="item" class="small-note">此处不模拟操作成功，不包含数据导入、审核或发布能力。</p><RouterLink to="/research/papers" class="button button-primary">返回研究工作台<AppIcon name="arrow"/></RouterLink><div v-if="item" class="placeholder-meta"><span>{{item.id}}</span><code>{{route.path}}</code></div></div>
  </section>
</template>
