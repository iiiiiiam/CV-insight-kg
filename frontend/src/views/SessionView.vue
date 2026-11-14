<script setup lang="ts">
import {ref} from 'vue'
import {useRouter} from 'vue-router'
import {auth,logout,refreshSession,runProbe} from '../stores/auth.ts'
import {ApiError} from '../services/http.ts'
import AppIcon from '../components/AppIcon.vue'
const router=useRouter(),busy=ref(false),error=ref('')
const result=ref<{username:string;message:string;checked_at:string;data_changed:boolean}|null>(null)
async function verify(){
  busy.value=true;error.value='';result.value=null
  try{result.value=await runProbe()}
  catch(e){error.value=e instanceof Error?e.message:'请求失败';if(e instanceof ApiError&&e.status===401)await router.replace('/admin/login')}
  finally{busy.value=false}
}
async function leave(){
  busy.value=true;error.value=''
  try{await logout();await router.replace('/admin/login')}
  catch(e){error.value=e instanceof Error?e.message:'退出失败'}finally{busy.value=false}
}
</script>
<template>
  <section class="standard-page">
    <div class="page-heading"><div><div class="eyebrow">IDENTITY & ACCESS</div><h1>会话与权限验证<span class="badge badge-teal">NAV20 · 已实现</span></h1><p>独立验证后台管理员权限，供数据管理接口接入。</p></div></div>
    <div class="session-grid">
      <section class="panel session-card"><div class="session-card-head"><span class="login-shield"><AppIcon name="shield" :size="25"/></span><span class="badge badge-teal">会话有效</span></div><h2>当前管理员</h2><p class="session-user">{{auth.session?.username}}</p><dl class="definition-list"><dt>角色</dt><dd>管理员 admin</dd><dt>到期时间</dt><dd>{{auth.session?new Date(auth.session.expires_at).toLocaleString('zh-CN'):'—'}}</dd><dt>登录状态</dt><dd>服务端验证</dd><dt>会话方式</dt><dd>HttpOnly Cookie</dd></dl><div class="session-actions"><button class="button button-secondary" :disabled="busy" @click="refreshSession(true)"><AppIcon name="refresh"/>刷新状态</button><button class="text-button" :disabled="busy" @click="leave"><AppIcon name="logout"/>退出当前会话</button></div></section>
      <section class="panel probe-card"><span class="eyebrow">PROTECTED ENDPOINT</span><h2>测试受保护操作</h2><p class="body-copy">发送一个需要管理员身份与CSRF校验的请求，检查登录状态是否由后台实际执行。</p><div class="endpoint-label"><span>POST</span><code>/api/admin/probe</code></div><button class="button button-primary" :disabled="busy" @click="verify"><AppIcon v-if="!busy" name="shield"/><span v-else class="spinner small"></span>{{busy?'正在校验…':'验证管理员权限'}}</button>
        <div v-if="result" class="probe-result" role="status"><span class="result-title"><AppIcon name="check"/>验证通过</span><p>{{result.message}}</p><small>{{new Date(result.checked_at).toLocaleString('zh-CN')}} · {{result.username}}</small></div>
        <div v-if="error" class="inline-error" role="alert"><AppIcon name="info"/><span>{{error}}</span></div>
        <p class="small-note">该测试不修改研究数据。基准清单、导入、重试及 B 候选接口已接入同一鉴权；可从数据管理菜单进入。</p>
      </section>
    </div>
    <div class="panel acceptance-card"><h2>这部分怎样验收</h2><ol><li>未登录直接请求受保护接口，应返回401。</li><li>登录后点击权限验证，应成功返回管理员身份。</li><li>退出后再次请求受保护接口，应被拒绝。</li><li>即使重放退出前的旧Cookie，后台仍应拒绝。</li></ol></div>
  </section>
</template>
