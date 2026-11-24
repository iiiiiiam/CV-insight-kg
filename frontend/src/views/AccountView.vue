<script setup lang="ts">
import {ref} from 'vue'
import {useRouter} from 'vue-router'
import {auth,logout,refreshSession} from '../stores/auth.ts'
import AppIcon from '../components/AppIcon.vue'

const router=useRouter(),busy=ref(false),error=ref('')
async function leave(){
  busy.value=true;error.value=''
  try{await logout();await router.replace('/login')}
  catch(e){error.value=e instanceof Error?e.message:'退出失败，请稍后重试。'}
  finally{busy.value=false}
}
</script>

<template>
  <section class="standard-page account-page">
    <div class="page-heading"><div><div class="eyebrow">ACCOUNT</div><h1>账号与登录状态</h1><p>查看当前会话身份和可用权限。</p></div></div>
    <section v-if="auth.session" class="panel account-card">
      <span class="account-avatar"><AppIcon :name="auth.session.role==='admin'?'shield':'user'" :size="30"/></span>
      <div><span class="badge badge-teal">会话有效</span><h2>{{auth.session.display_name}}</h2><p class="username">@{{auth.session.username}}</p></div>
      <dl class="definition-list"><dt>账号类型</dt><dd>{{auth.session.role==='admin'?'管理员':'普通用户'}}</dd><dt>可用范围</dt><dd>{{auth.session.role==='admin'?'研究页面及全部管理功能':'公开研究、知识证据和用户反馈'}}</dd><dt>会话到期</dt><dd>{{new Date(auth.session.expires_at).toLocaleString('zh-CN')}}</dd><dt>会话方式</dt><dd>服务端会话与HttpOnly Cookie</dd></dl>
      <p v-if="auth.session.role==='user'" class="permission-note">普通用户不能访问论文导入、批次撤回和反馈处理。个人图谱调整仍只保存在当前浏览器。</p>
      <p v-if="error" class="inline-error">{{error}}</p>
      <div class="account-actions"><button class="button button-secondary" :disabled="busy" @click="refreshSession(true)"><AppIcon name="refresh"/>刷新状态</button><RouterLink v-if="auth.session.role==='admin'" class="button button-secondary" to="/admin/access-check">管理员权限检查</RouterLink><button class="text-button" :disabled="busy" @click="leave"><AppIcon name="logout"/>退出登录</button></div>
    </section>
    <section v-else class="panel account-card signed-out"><AppIcon name="user" :size="42"/><h2>当前未登录</h2><p>研究页面可以直接浏览；登录普通用户账号可建立明确的参与身份。</p><div><RouterLink class="button button-primary" to="/login">普通用户登录</RouterLink><RouterLink class="button button-secondary" to="/register">注册账号</RouterLink><RouterLink class="text-button" to="/admin/login">管理员登录</RouterLink></div></section>
  </section>
</template>

<style scoped>
.account-page{max-width:980px}.account-card{max-width:680px;padding:28px}.account-avatar{display:grid;place-items:center;width:62px;height:62px;border-radius:18px;background:#eaf5f1;color:#398d79;margin-bottom:18px}.account-card h2{margin:12px 0 4px;font-size:25px}.username{color:#8297a0}.account-card .definition-list{grid-template-columns:90px 1fr;margin:28px 0}.permission-note{padding:13px;background:#f4f8f6;border:1px solid #deebe6;border-radius:8px;font-size:12px;line-height:1.8;color:#5e776e}.account-actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-top:22px}.signed-out{text-align:center}.signed-out>svg{color:#88a6a1}.signed-out p{margin:12px 0 24px;color:#789098}.signed-out>div{display:flex;justify-content:center;align-items:center;gap:12px;flex-wrap:wrap}
</style>
