import { reactive } from 'vue'
import type { AdminSession } from '../types.ts'
import { ApiError, requestJson } from '../services/http.ts'

export const auth=reactive({session:null as AdminSession|null,loaded:false,backend:'checking' as 'checking'|'online'|'offline',error:''})
let pending:Promise<void>|null=null
let generation=0
export function refreshSession(force=false):Promise<void>{
  if(pending)return pending
  if(auth.loaded&&!force)return Promise.resolve()
  const current=generation
  pending=(async()=>{
    try{const session=await requestJson<AdminSession>('/api/admin/session');if(current===generation){auth.session=session;auth.backend='online';auth.error=''}}
    catch(e){
      if(current===generation){
        auth.session=null
        if(e instanceof ApiError&&e.status===401){auth.backend='online';auth.error=''}
        else{auth.backend='offline';auth.error='鉴权服务未连接，请启动本地FastAPI服务后重试。'}
      }
    }finally{auth.loaded=true;pending=null}
  })()
  return pending
}
export async function login(username:string,password:string){
  generation++
  auth.session=await requestJson<AdminSession>('/api/admin/sessions',{method:'POST',body:JSON.stringify({username,password})})
  auth.backend='online';auth.error='';auth.loaded=true
}
export async function logout(){
  generation++
  try{await requestJson<void>('/api/admin/session',{method:'DELETE',headers:{'X-CSRF-Token':auth.session?.csrf_token??''}})}
  catch(e){if(!(e instanceof ApiError&&e.status===401))throw e}
  auth.session=null;auth.loaded=true
}
export async function runProbe(){
  try{return await requestJson<{ok:boolean;username:string;message:string;checked_at:string;data_changed:boolean}>('/api/admin/probe',{
    method:'POST',headers:{'X-CSRF-Token':auth.session?.csrf_token??''},body:JSON.stringify({purpose:'local-prototype-verification'})})}
  catch(e){if(e instanceof ApiError&&e.status===401)auth.session=null;throw e}
}
