<script setup lang="ts">
import {computed,ref} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {auth,adminLogin,refreshSession} from '../stores/auth.ts'
import {ApiError} from '../services/http.ts'
import AppIcon from '../components/AppIcon.vue'

const username=ref('admin'),password=ref(''),busy=ref(false),error=ref(''),visible=ref(false)
const route=useRoute(),router=useRouter()
const destination=computed(()=>{
  const value=String(route.query.redirect??'/admin/access-check')
  return value.startsWith('/')&&!value.startsWith('//')&&!value.startsWith('/admin/login')?value:'/admin/access-check'
})
async function submit(){
  if(!username.value.trim()||!password.value){error.value='请输入账号和密码。';return}
  busy.value=true;error.value=''
  try{await adminLogin(username.value.trim(),password.value);password.value='';await router.replace(destination.value)}
  catch(e){error.value=e instanceof ApiError?e.message:'无法连接鉴权服务，请启动本地后台后重试。'}
  finally{busy.value=false}
}
</script>
<template>
  <section class="login-page">
    <div class="login-intro"><div class="eyebrow">ADMIN WORKSPACE</div><h1>为数据管理建立<br><em>清晰的访问边界。</em></h1><p>研究探索保持开放。管理员会话用于保护数据导入和维护操作。</p><ul><li><AppIcon name="check"/>后台校验账号与权限</li><li><AppIcon name="check"/>登录后进入管理工作区</li><li><AppIcon name="check"/>退出后原会话失效</li></ul><div class="login-pattern" aria-hidden="true"><span></span><span></span><span></span><i></i><i></i></div></div>
    <div class="login-card">
      <span class="login-shield"><AppIcon name="shield" :size="28"/></span>
      <h2>管理员登录</h2><p class="muted">使用分配给你的管理员账号继续。</p>
      <template v-if="auth.session?.role==='admin'"><div class="inline-success"><AppIcon name="check"/>你已以 {{auth.session.username}} 身份登录。</div><RouterLink :to="destination" class="button button-primary full-width">进入管理工作区<AppIcon name="arrow"/></RouterLink></template>
      <form v-else @submit.prevent="submit">
        <p v-if="auth.session?.role==='user'" class="inline-error">当前登录的是普通用户 {{auth.session.display_name}}。验证管理员账号后将切换会话。</p>
        <label class="form-label" for="username">管理员账号</label><input id="username" v-model="username" class="form-input" name="username" autocomplete="username" maxlength="100" required :disabled="busy"/>
        <label class="form-label" for="password">密码</label><div class="password-field"><input id="password" v-model="password" class="form-input" name="password" :type="visible?'text':'password'" autocomplete="current-password" maxlength="256" required :disabled="busy"/><button type="button" :aria-label="visible?'隐藏密码':'显示密码'" @click="visible=!visible">{{visible?'隐藏':'显示'}}</button></div>
        <div v-if="error" class="inline-error" role="alert"><AppIcon name="info" :size="16"/><span>{{error}}</span></div>
        <button class="button button-primary full-width login-submit" type="submit" :disabled="busy"><span v-if="busy" class="spinner small"></span>{{busy?'正在验证…':'登录工作区'}}<AppIcon v-if="!busy" name="arrow"/></button>
      </form>
      <div class="login-bottom"><AppIcon name="shield" :size="14"/><span>请妥善保管你的账号与密码</span></div>
      <button v-if="auth.backend==='offline'" class="text-button health-retry" @click="refreshSession(true)"><AppIcon name="refresh" :size="14"/>重新检测后台连接</button>
      <RouterLink to="/research/papers" class="back-to-research">返回只读研究工作台</RouterLink>
      <RouterLink to="/login" class="back-to-research">普通用户登录或注册</RouterLink>
    </div>
  </section>
</template>
