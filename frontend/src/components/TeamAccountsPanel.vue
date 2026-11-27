<script setup lang="ts">
import {ref} from 'vue'
import {useRouter} from 'vue-router'
import {auth,logout} from '../stores/auth.ts'
import {listTeamAccounts,createTeamAccount,updateTeamAccount,changeTeamPassword} from '../services/knowledge-feedback.ts'
import type {TeamAccount} from '../services/knowledge-feedback.ts'
defineProps<{canManage:boolean}>()
const router=useRouter(),rows=ref<TeamAccount[]>([]),current=ref(''),busy=ref(false),error=ref(''),notice=ref('')
const username=ref(''),password=ref(''),role=ref<'owner'|'admin'>('admin'),resetName=ref(''),resetPassword=ref('')
const oldPassword=ref(''),newPassword=ref(''),confirmPassword=ref('')
const csrf=()=>auth.session?.csrf_token??''
const label=(value:string)=>value==='owner'?'账号管理员':'反馈管理员'
function fail(e:unknown){error.value=e instanceof Error?e.message:'操作未完成，请刷新后核对。'}
function remember(account:TeamAccount){const index=rows.value.findIndex(row=>row.username===account.username);if(index<0)rows.value.push(account);else rows.value[index]=account}
async function load(){if(busy.value)return;busy.value=true;error.value='';try{const result=await listTeamAccounts(csrf());rows.value=result.accounts;current.value=result.current_username;notice.value='账号列表已更新。'}catch(e){fail(e)}finally{busy.value=false}}
async function create(){
  if(busy.value)return;busy.value=true;error.value=''
  try{remember((await createTeamAccount({username:username.value,password:password.value,role:role.value},csrf())).account);username.value='';notice.value='已添加一个账号，其他账号保持原样。'}
  catch(e){fail(e)}finally{password.value='';busy.value=false}
}
async function update(row:TeamAccount,changes:{role?:'owner'|'admin';enabled?:boolean;new_password?:string}){
  if(busy.value)return;busy.value=true;error.value=''
  try{remember((await updateTeamAccount(row.username,{expected_revision:row.revision,...changes},csrf())).account);notice.value='该账号已更新；旧登录已失效，其他账号不受影响。'}
  catch(e){fail(e)}finally{resetPassword.value='';resetName.value='';busy.value=false}
}
async function changePassword(){
  if(busy.value)return;error.value=''
  if(newPassword.value!==confirmPassword.value){error.value='两次新密码不一致。';return}
  busy.value=true
  try{await changeTeamPassword({current_password:oldPassword.value,new_password:newPassword.value},csrf());await logout();await router.push('/admin/login')}
  catch(e){fail(e)}finally{oldPassword.value='';newPassword.value='';confirmPassword.value='';busy.value=false}
}
</script>
<template>
  <section class="team-accounts">
    <details v-if="canManage">
      <summary>管理员账号管理</summary>
      <p>管理团队成员的登录权限，每个人使用自己的账号。</p>
      <button type="button" class="button button-secondary" :disabled="busy" @click="load">查询管理员列表</button>
      <article v-for="row in rows" :key="row.username">
        <strong>{{row.username}}</strong> · {{label(row.role)}} · {{row.enabled?'启用':'停用'}}
        <template v-if="row.username!==current">
          <button type="button" class="button button-secondary" :disabled="busy" @click="update(row,{enabled:!row.enabled})">{{row.enabled?'停用':'启用'}}</button>
          <button type="button" class="button button-secondary" :disabled="busy" @click="update(row,{role:row.role==='owner'?'admin':'owner'})">{{row.role==='owner'?'设为反馈管理员':'允许管理账号'}}</button>
          <button type="button" class="button button-secondary" :disabled="busy" @click="resetName=row.username">重置密码</button>
          <form v-if="resetName===row.username" @submit.prevent="update(row,{new_password:resetPassword})"><label>新密码<input v-model="resetPassword" type="password" autocomplete="new-password" minlength="12" maxlength="256" required :disabled="busy"/></label><button class="button button-primary" :disabled="busy">确认重置此账号密码</button></form>
        </template>
        <span v-else>（当前账号）</span>
      </article>
      <form @submit.prevent="create">
        <h3>新增管理员</h3>
        <label>登录名<input v-model="username" pattern="[a-z][a-z0-9_.-]{2,49}" required autocomplete="off" :disabled="busy" placeholder="小写字母开头，3–50 位"/></label>
        <label>初始密码<input v-model="password" type="password" autocomplete="new-password" minlength="12" maxlength="256" required :disabled="busy"/></label>
        <label>权限<select v-model="role" :disabled="busy"><option value="admin">反馈管理员</option><option value="owner">账号管理员（可管理其他账号）</option></select></label>
        <button class="button button-primary" :disabled="busy">新增这个账号</button>
      </form>
    </details>
    <details><summary>修改我的密码</summary><form @submit.prevent="changePassword">
      <label>当前密码<input v-model="oldPassword" type="password" autocomplete="current-password" required maxlength="256" :disabled="busy"/></label>
      <label>新密码<input v-model="newPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="256" :disabled="busy"/></label>
      <label>确认新密码<input v-model="confirmPassword" type="password" autocomplete="new-password" required minlength="12" maxlength="256" :disabled="busy"/></label>
      <p>修改成功后需重新登录。</p><button class="button button-primary" :disabled="busy">保存并重新登录</button>
    </form></details>
    <p v-if="error" role="alert">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
  </section>
</template>
<style scoped>
.team-accounts{margin-top:20px;font-size:14px;line-height:1.7}
.team-accounts details{margin:16px 0;padding:18px 20px;border:1px solid #dce8e5;border-radius:10px}
.team-accounts summary{cursor:pointer;font-size:16px;font-weight:600;line-height:1.5}
.team-accounts form{margin-top:20px;max-width:560px}
.team-accounts h3{margin:24px 0 16px;font-size:16px;line-height:1.5}
.team-accounts label{display:block;margin:16px 0;font-size:14px}
.team-accounts input,.team-accounts select{display:block;box-sizing:border-box;width:100%;max-width:100%;min-height:44px;margin-top:8px;padding:10px 12px;background:#fff;border:1px solid #cedfd7;border-radius:8px;color:inherit;font:inherit;line-height:1.5}
.team-accounts .button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:10px 16px;font-size:14px;line-height:1.5}
.team-accounts article{margin:12px 0;padding:16px;border:1px solid #dce8e5;border-radius:8px;overflow-wrap:anywhere}
.team-accounts article .button{margin:6px 0 6px 8px}
.team-accounts p{margin:12px 0;font-size:14px;line-height:1.8}
.team-accounts [role=alert]{color:#a34137}.team-accounts [role=status]{color:#35694e}
@media(max-width:600px){.team-accounts details{padding:16px}.team-accounts article .button{margin:8px 8px 0 0}}
</style>
