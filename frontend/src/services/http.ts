export class ApiError extends Error {
  status:number;requestId:string
  constructor(message:string,status:number,requestId=''){super(message);this.name='ApiError';this.status=status;this.requestId=requestId}
}
export async function requestJson<T>(url:string,init:RequestInit={}):Promise<T>{
  const headers=new Headers(init.headers)
  if(init.body)headers.set('Content-Type','application/json')
  const response=await fetch(url,{...init,headers,credentials:'same-origin',signal:init.signal??AbortSignal.timeout(8000)})
  if(response.status===204)return undefined as T
  const payload=await response.json().catch(()=>null)
  if(!response.ok)throw new ApiError(payload?.error?.message??(typeof payload?.detail==='string'?payload.detail:null)??`请求失败（${response.status}）`,response.status,payload?.request_id??'')
  return payload as T
}
