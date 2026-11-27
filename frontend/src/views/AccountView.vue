<script setup lang="ts">
import {onMounted,ref,watch} from 'vue'
import {useRouter} from 'vue-router'
import {auth,logout,refreshSession} from '../stores/auth.ts'
import AppIcon from '../components/AppIcon.vue'
import TeamAccountsPanel from '../components/TeamAccountsPanel.vue'
import {getCloudFeedbackConfig} from '../services/knowledge-feedback.ts'

const router=useRouter(),busy=ref(false),error=ref('')
const teamEnabled=ref(false),canManage=ref(false),accountError=ref('')
let configVersion=0
async function loadAccountOptions(){
 const version=++configVersion;teamEnabled.value=false;canManage.value=false;accountError.value=''
 if(auth.session?.role!=='admin')return
 try{const config=await getCloudFeedbackConfig();if(version!==configVersion)return;teamEnabled.value=config.team_enabled;canManage.value=config.account_management}
 catch{if(version===configVersion)accountError.value='账号管理暂不可用，请刷新页面重试。'}
}
onMounted(loadAccountOptions)
watch(()=>auth.session?.username,loadAccountOptions)
async function leave(){
  busy.value=true;error.value=''
  try{await logout();await router.replace('/login')}
  catch(e){error.value=e instanceof Error?e.message:'退出失败，请稍后重试。'}
  finally{busy.value=false}
}
</script>

<template>
  <section class="standard-page account-page">
    <div class="page-heading"><div><div class="eyebrow">ACCOUNT</div><h1>账号与安全</h1><p>查看登录状态、管理团队账号与密码。</p></div></div>
    <section v-if="auth.session" class="panel account-card">
      <span class="account-avatar"><AppIcon :name="auth.session.role==='admin'?'shield':'user'" :size="30"/></span>
      <div><span class="badge badge-teal">会话有效</span><h2>{{auth.session.display_name}}</h2><p class="username">@{{auth.session.username}}</p></div>
      <dl class="definition-list"><dt>账号类型</dt><dd>{{auth.session.role==='admin'?'管理员':'普通用户'}}</dd><dt>可用范围</dt><dd>{{auth.session.role==='admin'?'管理功能按账号权限开放':'公开研究、知识证据和用户反馈'}}</dd><dt>会话到期</dt><dd>{{new Date(auth.session.expires_at).toLocaleString('zh-CN')}}</dd></dl>
      <p v-if="auth.session.role==='user'" class="permission-note">普通用户不能访问论文导入、批次撤回和反馈处理。个人图谱调整仍只保存在当前浏览器。</p>
      <p v-if="error" class="inline-error">{{error}}</p>
      <div class="account-actions"><button class="button button-secondary" :disabled="busy" @click="refreshSession(true)"><AppIcon name="refresh"/>刷新状态</button><RouterLink v-if="auth.session.role==='admin'" class="button button-secondary" to="/admin/access-check">管理员权限检查</RouterLink><button class="text-button" :disabled="busy" @click="leave"><AppIcon name="logout"/>退出登录</button></div>
    </section>
    <section v-else class="panel account-card signed-out"><AppIcon name="user" :size="42"/><h2>当前未登录</h2><p>研究页面可以直接浏览；登录普通用户账号可建立明确的参与身份。</p><div><RouterLink class="button button-primary" to="/login">普通用户登录</RouterLink><RouterLink class="button button-secondary" to="/register">注册账号</RouterLink><RouterLink class="text-button" to="/admin/login">管理员登录</RouterLink></div></section>
    <section v-if="auth.session?.role==='admin'&&teamEnabled" class="panel security-card"><h2>{{canManage?'团队账号与密码':'我的登录密码'}}</h2><p>使用各自的账号登录；密码修改后需重新登录。</p><TeamAccountsPanel :can-manage="canManage"/></section>
    <p v-if="accountError" class="inline-error" role="alert">{{accountError}}</p>
  </section>
</template>

<style scoped>
.account-page{max-width:980px;font-size:15px;line-height:1.7}
.account-card,.security-card{width:100%;max-width:none;box-sizing:border-box;padding:28px}
.security-card{margin-top:24px}
.account-card h2,.security-card h2{font-size:20px;line-height:1.5;margin:0 0 8px}
.account-avatar{display:grid;place-items:center;width:56px;height:56px;border-radius:16px;background:#eaf5f1;color:#398d79;margin-bottom:16px}
.account-card h2{margin:12px 0 4px;font-size:24px}
.username{color:#789098;margin:0;font-size:14px}
.security-card>p{color:#648075;margin:8px 0 0;font-size:14px;line-height:1.7}
.account-card .definition-list{grid-template-columns:100px minmax(0,1fr);gap:12px 20px;margin:24px 0;font-size:14px;line-height:1.7}
.account-card .definition-list dt,.account-card .definition-list dd{margin:0;overflow-wrap:anywhere}
.permission-note{padding:12px;background:#f4f8f6;border:1px solid #deebe6;border-radius:8px;font-size:13px;line-height:1.8;color:#5e776e}
.account-actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-top:24px}
.account-actions .button,.account-actions .text-button{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:10px 16px;box-sizing:border-box;font-size:14px;line-height:1.5}
.signed-out{text-align:center}.signed-out>svg{color:#88a6a1}.signed-out p{margin:12px 0 24px;color:#789098}.signed-out>div{display:flex;justify-content:center;align-items:center;gap:12px;flex-wrap:wrap}
@media(max-width:600px){.account-card,.security-card{padding:20px}.account-card .definition-list{grid-template-columns:80px minmax(0,1fr);gap:12px}.account-actions .button{flex:1 1 auto}}
</style>
