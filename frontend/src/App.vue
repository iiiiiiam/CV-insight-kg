<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {RouterLink,RouterView,useRoute,useRouter} from 'vue-router'
import {MENU} from './navigation.ts'
import type {MenuItem} from './navigation.ts'
import {auth,logout,refreshSession} from './stores/auth.ts'
import AppIcon from './components/AppIcon.vue'

const route=useRoute(),router=useRouter(),mobileOpen=ref(false),query=ref(''),notice=ref('')
const collapsed=ref<string[]>(['数据管理','系统管理'])
const groups=computed(()=>[...new Set(MENU.map(n=>n.group))].map(group=>({name:group,
  sections:[...new Set(MENU.filter(n=>n.group===group).map(n=>n.section))].map(section=>({name:section,items:MENU.filter(n=>n.group===group&&n.section===section)}))})))
function toggle(group:string){collapsed.value=collapsed.value.includes(group)?collapsed.value.filter(x=>x!==group):[...collapsed.value,group]}
function active(item:MenuItem){
  const [path,queryString='']=item.path.split('?')
  if(item.id==='NAV03')return route.path.startsWith('/research/papers/')
  return route.path===path&&String(route.query.view??'')===(new URLSearchParams(queryString).get('view')??'')
}
async function leave(){try{await logout();notice.value='已退出管理员会话。';if(route.meta.requiresAuth)await router.push('/research/papers')}catch{notice.value='退出失败，请检查鉴权服务后重试。'}}
function search(){router.push({path:'/research/papers',query:query.value.trim()?{q:query.value.trim()}:{}})}
onMounted(()=>void refreshSession())
watch(()=>auth.session,session=>{if(!session&&auth.loaded&&route.meta.requiresAuth)void router.replace({path:'/admin/login',query:{redirect:route.fullPath}})})
</script>
<template>
  <div class="app-shell">
    <div v-if="mobileOpen" class="mobile-backdrop" @click="mobileOpen=false"></div>
    <aside class="sidebar" :class="{open:mobileOpen}">
      <RouterLink class="brand" to="/research/papers" @click="mobileOpen=false"><span class="brand-mark"><AppIcon name="graph" :size="27"/></span><span><strong>知域 <em>Atlas</em></strong><small>CV 知识图谱</small></span></RouterLink>
      <div class="sidebar-caption">研究导航 <span>PROTOTYPE</span></div>
      <nav aria-label="三级功能菜单" class="nav-scroll">
        <section v-for="group in groups" :key="group.name" class="nav-group">
          <button class="nav-group-title" :aria-expanded="!collapsed.includes(group.name)" @click="toggle(group.name)"><AppIcon :name="group.name==='文献调研'?'book':group.name==='研究分析'?'graph':group.name==='数据管理'?'layers':'shield'"/><span>{{group.name}}</span><AppIcon name="down" :size="14" :class="{turned:collapsed.includes(group.name)}"/></button>
          <div v-if="!collapsed.includes(group.name)" class="nav-sections">
            <div v-for="section in group.sections" :key="section.name" class="nav-section">
              <div class="nav-section-name">{{section.name}}</div>
              <RouterLink v-for="item in section.items" :key="item.id" :to="item.path" class="nav-item" :class="{active:active(item)}" :title="`${item.id} · ${item.owner}`" @click="mobileOpen=false">
                <span>{{item.label}}</span><small v-if="!item.implemented">待实现</small><i v-else-if="active(item)"></i>
              </RouterLink>
            </div>
          </div>
        </section>
      </nav>
      <div class="sidebar-foot"><span class="member-avatar">D</span><div><strong>成员 D · 本轮原型</strong><small>A / B 已接入 · C 待接入</small></div><span class="online-dot"></span></div>
    </aside>
    <div class="main-shell">
      <header class="topbar">
        <div class="breadcrumb"><button class="icon-button mobile-menu" aria-label="打开导航" @click="mobileOpen=true"><AppIcon name="menu"/></button><span>工作空间</span><AppIcon name="chevron" :size="13"/><strong>{{route.meta.title}}</strong></div>
        <form class="top-search" role="search" @submit.prevent="search"><AppIcon name="search" :size="16"/><input v-model="query" aria-label="全局搜索论文" placeholder="搜索标题或摘要关键词…"/><kbd>Enter</kbd></form>
        <div class="top-actions"><span class="mode-label"><i></i>真实数据</span>
          <template v-if="auth.session"><RouterLink to="/admin/access-check" class="account-button"><AppIcon name="shield" :size="16"/>{{auth.session.username}}</RouterLink><button class="icon-button" aria-label="退出登录" @click="leave"><AppIcon name="logout"/></button></template>
          <RouterLink v-else to="/admin/login" class="account-button"><AppIcon name="user" :size="16"/>管理员登录</RouterLink>
        </div>
      </header>
      <div v-if="notice" class="global-notice" role="status">{{notice}}<button class="icon-button" aria-label="关闭提示" @click="notice=''"><AppIcon name="close" :size="14"/></button></div>
      <main id="main-content"><RouterView/></main>
      <footer class="app-footer"><span>知域 Atlas · CV 研究探索原型</span><span>A 论文元数据 · B 待审核候选 · C 待接入</span></footer>
    </div>
  </div>
</template>
