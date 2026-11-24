import assert from 'node:assert/strict'
import test from 'node:test'
import {auth,logout,registerUser,userLogin} from '../src/stores/auth.ts'

const user={authenticated:true as const,username:'reader01',display_name:'研究用户',role:'user' as const,
  csrf_token:'csrf',expires_at:'2026-12-01T00:00:00Z',user_id:'usr_1',feedback_token:'a'.repeat(64)}

test('ordinary registration, login and logout use role-separated session endpoints',async()=>{
  const previous=globalThis.fetch,calls:Array<{url:string;init?:RequestInit}>=[]
  globalThis.fetch=async(input,init)=>{
    calls.push({url:String(input),init})
    return String(input)==='/api/session'&&init?.method==='DELETE'
      ?new Response(null,{status:204})
      :Response.json(user,{status:String(input)==='/api/users'?201:200})
  }
  try{
    await registerUser('reader01','研究用户','Reader2026')
    assert.equal(auth.session?.role,'user')
    assert.deepEqual(JSON.parse(String(calls[0]!.init?.body)),{username:'reader01',display_name:'研究用户',password:'Reader2026'})
    await userLogin('reader01','Reader2026')
    assert.equal(calls[1]!.url,'/api/user/sessions')
    await logout()
    assert.equal(calls[2]!.url,'/api/session')
    assert.equal(new Headers(calls[2]!.init?.headers).get('X-CSRF-Token'),'csrf')
    assert.equal(auth.session,null)
  }finally{globalThis.fetch=previous;auth.session=null;auth.loaded=false}
})
