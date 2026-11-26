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
    <div class="page-heading"><div><div class="eyebrow">IDENTITY & ACCESS</div><h1>会话与权限验证</h1><p>查看管理员登录状态与访问权限。</p></div></div>
    <div class="session-grid">
      <section class="panel session-card"><div class="session-card-head"><span class="login-shield"><AppIcon name="shield" :size="25"/></span><span class="badge badge-teal">会话有效</span></div><h2>当前管理员</h2><p class="session-user">{{auth.session?.username}}</p><dl class="definition-list"><dt>角色</dt><dd>管理员</dd><dt>到期时间</dt><dd>{{auth.session?new Date(auth.session.expires_at).toLocaleString('zh-CN'):'—'}}</dd><dt>登录状态</dt><dd>服务端验证</dd></dl><div class="session-actions"><button class="button button-secondary" :disabled="busy" @click="refreshSession(true)"><AppIcon name="refresh"/>刷新状态</button><button class="text-button" :disabled="busy" @click="leave"><AppIcon name="logout"/>退出当前会话</button></div></section>
      <section class="panel probe-card"><h2>检查访问权限</h2><p class="body-copy">确认当前账号可以使用管理功能。</p><button class="button button-primary" :disabled="busy" @click="verify"><AppIcon v-if="!busy" name="shield"/><span v-else class="spinner small"></span>{{busy?'正在校验…':'验证管理员权限'}}</button>
        <div v-if="result" class="probe-result" role="status"><span class="result-title"><AppIcon name="check"/>验证通过</span><p>当前账号拥有管理员访问权限。</p><small>{{new Date(result.checked_at).toLocaleString('zh-CN')}} · {{result.username}}</small></div>
        <div v-if="error" class="inline-error" role="alert"><AppIcon name="info"/><span>{{error}}</span></div>

      </section>
    </div>
  </section>
</template>
