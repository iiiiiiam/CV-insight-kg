<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {auth,registerUser,userLogin} from '../stores/auth.ts'
import {ApiError} from '../services/http.ts'
import AppIcon from '../components/AppIcon.vue'

const route=useRoute(),router=useRouter()
const mode=ref<'login'|'register'>(route.path==='/register'?'register':'login')
const username=ref(''),displayName=ref(''),password=ref(''),confirmation=ref('')
const visible=ref(false),busy=ref(false),error=ref('')
const destination=computed(()=>{
  const value=String(route.query.redirect??'/research/papers')
  return value.startsWith('/')&&!value.startsWith('//')&&!value.startsWith('/login')&&!value.startsWith('/register')?value:'/research/papers'
})
watch(mode,()=>{error.value='';password.value='';confirmation.value=''})
function change(value:'login'|'register'){
  mode.value=value
  void router.replace({path:value==='register'?'/register':'/login',query:route.query})
}
async function submit(){
  const name=username.value.trim(),shown=displayName.value.trim()
  if(!name||!password.value||(mode.value==='register'&&!shown)){error.value='请完整填写账号信息。';return}
  if(mode.value==='register'&&password.value!==confirmation.value){error.value='两次输入的密码不一致。';return}
  busy.value=true;error.value=''
  try{
    if(mode.value==='register')await registerUser(name,shown,password.value)
    else await userLogin(name,password.value)
    password.value='';confirmation.value='';await router.replace(destination.value)
  }catch(e){error.value=e instanceof ApiError?e.message:'无法连接登录服务，请检查D后端。'}
  finally{busy.value=false}
}
</script>

<template>
  <section class="login-page user-login-page">
    <div class="login-intro"><div class="eyebrow">RESEARCH ACCOUNT</div><h1>保存你的研究身份，<br><em>参与知识反馈。</em></h1><p>普通用户可以浏览全部公开研究页面、提交反馈并查看登录状态；数据导入、批次和反馈处理仍只对管理员开放。</p><ul><li><AppIcon name="check"/>账号密码仅保存在本地D服务</li><li><AppIcon name="check"/>普通账号不具备管理权限</li><li><AppIcon name="check"/>研究检索不登录也可以使用</li></ul><div class="login-pattern" aria-hidden="true"><span></span><span></span><span></span><i></i><i></i></div></div>
    <div class="login-card">
      <span class="login-shield user-mark"><AppIcon name="user" :size="28"/></span>
      <div class="account-tabs" role="tablist" aria-label="普通用户账号操作"><button type="button" :aria-selected="mode==='login'" @click="change('login')">用户登录</button><button type="button" :aria-selected="mode==='register'" @click="change('register')">注册账号</button></div>
      <template v-if="auth.session">
        <div class="inline-success"><AppIcon name="check"/>当前已登录：{{auth.session.display_name}}（{{auth.session.role==='admin'?'管理员':'普通用户'}}）</div>
        <RouterLink to="/account" class="button button-primary full-width">查看账号状态<AppIcon name="arrow"/></RouterLink>
      </template>
      <form v-else @submit.prevent="submit">
        <h2>{{mode==='register'?'创建普通用户账号':'普通用户登录'}}</h2><p class="muted">{{mode==='register'?'注册后将自动登录。':'使用已注册的本地账号继续。'}}</p>
        <label class="form-label" for="user-username">用户名</label><input id="user-username" v-model="username" class="form-input" autocomplete="username" minlength="3" maxlength="50" required :disabled="busy" placeholder="3—50个字符，不含空格"/>
        <template v-if="mode==='register'"><label class="form-label" for="display-name">显示名称</label><input id="display-name" v-model="displayName" class="form-input" autocomplete="name" maxlength="50" required :disabled="busy" placeholder="页面中显示的名称"/></template>
        <label class="form-label" for="user-password">密码</label><div class="password-field"><input id="user-password" v-model="password" class="form-input" :type="visible?'text':'password'" :autocomplete="mode==='register'?'new-password':'current-password'" minlength="8" maxlength="128" required :disabled="busy"/><button type="button" :aria-label="visible?'隐藏密码':'显示密码'" @click="visible=!visible">{{visible?'隐藏':'显示'}}</button></div>
        <template v-if="mode==='register'"><small class="password-note">至少8位，并同时包含字母和数字。</small><label class="form-label" for="password-confirmation">确认密码</label><input id="password-confirmation" v-model="confirmation" class="form-input" type="password" autocomplete="new-password" minlength="8" maxlength="128" required :disabled="busy"/></template>
        <div v-if="error" class="inline-error" role="alert"><AppIcon name="info" :size="16"/><span>{{error}}</span></div>
        <button class="button button-primary full-width login-submit" type="submit" :disabled="busy"><span v-if="busy" class="spinner small"></span>{{busy?'正在提交…':mode==='register'?'注册并登录':'登录'}}<AppIcon v-if="!busy" name="arrow"/></button>
      </form>
      <div class="login-bottom"><AppIcon name="shield" :size="14"/><span>会话使用HttpOnly Cookie，普通用户不能访问管理接口</span></div>
      <RouterLink to="/admin/login" class="back-to-research">管理员登录</RouterLink><RouterLink to="/research/papers" class="back-to-research">暂不登录，继续浏览</RouterLink>
    </div>
  </section>
</template>

<style scoped>
.user-mark{background:#edf2fb;color:#587cae}.account-tabs{display:grid;grid-template-columns:1fr 1fr;gap:6px;padding:4px;background:#f2f6f6;border-radius:9px;margin-bottom:24px}.account-tabs button{border:0;background:transparent;border-radius:7px;padding:10px;color:#6f8790;cursor:pointer}.account-tabs button[aria-selected=true]{background:white;color:#237e70;box-shadow:0 2px 8px #304c5512}.password-note{display:block;margin-top:7px;color:#82969e;font-size:10px}.login-card h2{margin-top:4px}.login-card>.back-to-research+.back-to-research{margin-top:10px}
</style>
