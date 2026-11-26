'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHandler } = require('./index');
const {scryptSync} = require('node:crypto');
const env = { CLOUDBASE_ENV_ID: 'offline-test', CLOUDBASE_APIKEY: 'fake-server-key',
  RI_FEEDBACK_PILOT_TOKEN: 'a'.repeat(64), RI_FEEDBACK_ADMIN_TOKEN: 'b'.repeat(64) };
const id = '11111111-1111-4111-8111-111111111111';
const body = { installation_id: '22222222-2222-4222-8222-222222222222', local_feedback_id: 'local-1',
  receipt_token: 'c'.repeat(64), payload: { message: 'Please review this label.' } };
function fixture(customEnv = env) {
  let row;
  const calls = [];
  const accountRows=new Map(Object.entries(JSON.parse(customEnv.RI_FEEDBACK_TEAM_USERS||'{}')).map(([username,user])=>
    [username,{username,...user,enabled:true,revision:0,created_at:'now',updated_at:'now'}]));
  const handler = createHandler({ env: customEnv, clock: () => new Date('2026-11-26T00:00:00Z'),
    fetchImpl: async (address, options) => {
      const url = new URL(address);
      assert.equal(url.hostname, 'offline-test.api.tcloudbasegateway.com');
      assert.equal(options.headers.Authorization, 'Bearer fake-server-key');
      assert.equal(options.redirect, 'error');
      calls.push({ url, options });
      if(url.pathname.endsWith('/ri_team_accounts')) {
        const username=url.searchParams.get('username');
        return Response.json([...accountRows.values()].filter(user=>!username||username===`eq.${user.username}`));
      }
      if(url.pathname.endsWith('/rpc/ri_team_manage')) {
        const body=JSON.parse(options.body),actor=accountRows.get(body.p_actor),target=accountRows.get(body.p_username);
        const error=code=>Response.json({error:code});
        if(!actor?.enabled||actor.revision!==body.p_actor_revision)return error('UNAUTHORIZED');
        if(body.p_action!=='password'&&actor.role!=='owner')return error('FORBIDDEN');
        if(body.p_action==='create') {
          if(target)return error('ACCOUNT_EXISTS');
          const added={username:body.p_username,password_hash:body.p_password_hash,role:body.p_role,enabled:true,revision:0,created_at:'now',updated_at:'now'};
          accountRows.set(added.username,added);return Response.json({account:added});
        }
        if(!target)return error('NOT_FOUND');
        if(target.revision!==body.p_expected_revision)return error('STATE_CONFLICT');
        if(target.username===actor.username&&(body.p_enabled===false||(body.p_role&&body.p_role!==actor.role)))return error('SELF_DISABLE');
        if(body.p_password_hash)target.password_hash=body.p_password_hash;
        if(body.p_role)target.role=body.p_role;
        if(body.p_enabled!==null)target.enabled=body.p_enabled;
        target.revision++;
        return Response.json({account:target});
      }
      let result = [];
      if (options.method === 'POST' && !row) {
        row = { ...JSON.parse(options.body), id, status: 'open', processing_note: '', state_revision: 0,
          created_at: '2026-11-26T00:00:00Z', updated_at: '2026-11-26T00:00:00Z' };
        result = [row];
      } else if (options.method === 'GET' && row) {
        result = !url.searchParams.has('id') || url.searchParams.get('id') === `eq.${row.id}` ? [row] : [];
      } else if (options.method === 'PATCH' && row && url.searchParams.get('id') === `eq.${row.id}`
        && url.searchParams.get('state_revision') === `eq.${row.state_revision}` && row.status !== 'withdrawn') {
        row = { ...row, ...JSON.parse(options.body) }; result = [row];
      }
      return Response.json(result);
    } });
  async function request(path, method = 'GET', data, admin = false, receipt = body.receipt_token) {
    return handler(new Request(`http://offline${path}`, { method, headers: {
      'content-type': 'application/json', 'x-ri-pilot-token': env.RI_FEEDBACK_PILOT_TOKEN,
      authorization: `Bearer ${admin ? env.RI_FEEDBACK_ADMIN_TOKEN : receipt}` },
    ...(data === undefined ? {} : { body: typeof data === 'string' ? data : JSON.stringify(data) }) }));
  }
  return { request, calls, handler, getRow: () => row, accountRows };
}
test('health is local readiness and never queries database', async () => {
  const f = fixture(); const response = await f.request('/health');
  assert.equal(response.status, 200); assert.equal(f.calls.length, 0);
  assert.equal((await response.json()).admin_configured, true);
});
test('complete submit, duplicate, team update and owner readback flow', async () => {
  const f = fixture();
  assert.equal((await f.request('/requests', 'POST', body)).status, 201);
  assert.notEqual(f.getRow().receipt_token_hash, body.receipt_token);
  assert.equal(f.getRow().receipt_token_hash.length, 64);
  const duplicate = await f.request('/requests', 'POST', body);
  assert.equal(duplicate.status, 200); assert.equal((await duplicate.json()).duplicate, true);
  assert.equal((await f.request('/requests', 'POST', { ...body, payload: { message: 'different' } })).status, 409);
  assert.equal((await f.request(`/requests/${id}`, 'GET', undefined, false, 'd'.repeat(64))).status, 404);
  const list = await (await f.request('/admin/requests', 'GET', undefined, true)).json();
  assert.equal(list.feedback[0].payload.message, body.payload.message);
  assert.equal(list.feedback[0].receipt_token_hash, undefined);
  const update = { status: 'resolved', processing_note: 'Reviewed and corrected.', expected_revision: 0 };
  assert.equal((await f.request(`/admin/requests/${id}`, 'PATCH', update, true)).status, 200);
  assert.equal((await f.request(`/admin/requests/${id}`, 'PATCH', update, true)).status, 409);
  const owner = await (await f.request(`/requests/${id}`)).json();
  assert.equal(owner.feedback.status, 'resolved'); assert.equal(owner.feedback.state_revision, 1);
  assert.equal(owner.feedback.processing_note, update.processing_note);
  assert.equal(owner.feedback.receipt_token_hash, undefined); assert.equal(owner.feedback.payload, undefined);
});
test('missing configuration and unauthorized requests fail before database access', async () => {
  const f = fixture({}); assert.equal((await f.request('/requests', 'POST', body)).status, 503);
  assert.equal(f.calls.length, 0);
  const configured = fixture();
  assert.equal((await configured.handler(new Request('http://offline/requests', { method: 'POST' }))).status, 401);
  assert.equal((await configured.request('/admin/requests')).status, 401);
  assert.equal(configured.calls.length, 0);
});
for (const [name, input, status] of [
  ['invalid JSON', '{', 400], ['array', [], 400], ['unknown field', { ...body, status: 'resolved' }, 400],
  ['bad installation', { ...body, installation_id: 'wrong' }, 400],
  ['missing message', { ...body, payload: {} }, 400],
  ['nested payload', { ...body, payload: { message: 'ok', category: {} } }, 400],
  ['oversized request', 'x'.repeat(4097), 413],
  ['oversized UTF8 payload', { ...body, payload: { message: '\u4e2d'.repeat(800) } }, 413],
]) test(name + ' rejected without database access', async () => {
  const f = fixture(); assert.equal((await f.request('/requests', 'POST', input)).status, status);
  assert.equal(f.calls.length, 0);
});
test('tokens in query strings rejected', async () => {
  const f = fixture(); assert.equal((await f.request('/health?token=secret')).status, 400);
  assert.equal(f.calls.length, 0);
});
test('database errors do not disclose backend response or credentials', async () => {
  for (const fetchImpl of [async () => new Response('private database details', { status: 500 }),
    async () => { throw new Error('private network details'); }]) {
    const handler = createHandler({ env, fetchImpl });
    const response = await handler(new Request('http://offline/admin/requests', {
      headers: { authorization: `Bearer ${env.RI_FEEDBACK_ADMIN_TOKEN}` } }));
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { error: 'DATABASE_UNAVAILABLE' });
  }
});
test('withdrawn records cannot be changed by team update', async () => {
  const f = fixture(); await f.request('/requests', 'POST', body); f.getRow().status = 'withdrawn';
  assert.equal((await f.request(`/admin/requests/${id}`, 'PATCH', {
    status: 'resolved', processing_note: 'note', expected_revision: 0 }, true)).status, 409);
});

const loginPassword = 'offline-team-password';
const loginSalt = Buffer.alloc(16, 1);
const loginEnv = {...env, RI_FEEDBACK_PUBLIC_ENABLED:'true', RI_FEEDBACK_TEAM_USERS:JSON.stringify({
  'team-admin':{role:'admin',password_hash:`scrypt$${loginSalt.toString('hex')}$${scryptSync(loginPassword,loginSalt,32).toString('hex')}`},
})};
function loginRequest(password=loginPassword){return new Request('https://offline/sessions',{
  method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({username:'team-admin',password}),
})}
test('normal software can submit and read its own reply without shared pilot key',async()=>{
  const f=fixture(loginEnv);
  const created=await f.handler(new Request('https://offline/requests',{
    method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),
  }));
  assert.equal(created.status,201);
  const own=await f.handler(new Request(`https://offline/requests/${id}`,{
    headers:{authorization:`Bearer ${body.receipt_token}`},
  }));
  assert.equal(own.status,200);
  const other=await f.handler(new Request(`https://offline/requests/${id}`,{
    headers:{authorization:`Bearer ${'d'.repeat(64)}`},
  }));
  assert.equal(other.status,404);
});
test('team login issues short-lived admin session, rejects incorrect password and forged token',async()=>{
  const f=fixture(loginEnv);
  assert.equal((await f.handler(loginRequest('incorrect'))).status,401);
  const logged=await f.handler(loginRequest());
  assert.equal(logged.status,200);
  const session=await logged.json();
  assert.equal(session.role,'admin');
  assert.ok(session.access_token.startsWith('ri1.'));
  assert.equal(f.calls.length,2); // One account lookup for each login attempt.
  const result=await f.handler(new Request('https://offline/admin/requests',{
    headers:{authorization:`Bearer ${session.access_token}`},
  }));
  assert.equal(result.status,200);
  assert.equal((await f.handler(new Request('https://offline/admin/requests',{
    headers:{authorization:`Bearer ${session.access_token}tampered`},
  }))).status,401);
});
test('expired team session cannot query database; removed account is rejected on next access',async()=>{
  const f=fixture(loginEnv),session=await (await f.handler(loginRequest())).json();
  const expired=createHandler({env:loginEnv,clock:()=>new Date(Date.now()+7200000),
    fetchImpl:async()=>assert.fail('Expired session queried database')});
  const req=()=>new Request('https://offline/admin/requests',{headers:{authorization:`Bearer ${session.access_token}`}});
  assert.equal((await expired(req())).status,401);
  f.accountRows.delete('team-admin');
  assert.equal((await f.handler(req())).status,401);
});
test('public submit and login rate limits reject requests before unlimited database work',async()=>{
  const f=fixture(loginEnv);
  let response;
  for(let i=0;i<11;i++)response=await f.handler(new Request('https://offline/requests',{
    method:'POST',headers:{'content-type':'application/json'},body:'{}',
  }));
  assert.equal(response.status,429);
  assert.equal(f.calls.length,0);
});

const ownerEnv={...loginEnv,RI_FEEDBACK_TEAM_USERS:JSON.stringify({
  'team-admin':{role:'owner',password_hash:JSON.parse(loginEnv.RI_FEEDBACK_TEAM_USERS)['team-admin'].password_hash},
})};
async function authed(f,token,path,method='GET',body){return f.handler(new Request('https://offline'+path,{
  method,headers:{authorization:`Bearer ${token}`,'content-type':'application/json'},
  ...(body===undefined?{}:{body:JSON.stringify(body)}),
}))}
test('account owner adds separately, duplicates do not overwrite and stale edits conflict',async()=>{
  const f=fixture(ownerEnv),token=(await (await f.handler(loginRequest())).json()).access_token;
  const created=await authed(f,token,'/admin/accounts','POST',{username:'colleague',password:'new-password-123',role:'admin'});
  assert.equal(created.status,200);
  assert.equal(f.accountRows.size,2);
  assert.equal(JSON.stringify(await created.json()).includes('password_hash'),false);
  const duplicate=await authed(f,token,'/admin/accounts','POST',{username:'colleague',password:'different-password',role:'owner'});
  assert.equal(duplicate.status,409);
  assert.equal(f.accountRows.get('colleague').role,'admin');
  assert.equal((await authed(f,token,'/admin/accounts/colleague','PATCH',{enabled:false,expected_revision:0})).status,200);
  assert.equal((await authed(f,token,'/admin/accounts/colleague','PATCH',{role:'owner',expected_revision:0})).status,409);
  assert.equal(f.accountRows.get('colleague').role,'admin');
  assert.equal((await authed(f,token,'/admin/accounts/team-admin','PATCH',{enabled:false,expected_revision:0})).status,409);
  assert.equal((await authed(f,token,'/admin/accounts/team-admin','PATCH',{new_password:'bypass-old-password',expected_revision:0})).status,403);
});
test('feedback admin cannot manage accounts; own password change revokes previous login',async()=>{
  const f=fixture(loginEnv),token=(await (await f.handler(loginRequest())).json()).access_token;
  assert.equal((await authed(f,token,'/admin/accounts')).status,403);
  assert.equal((await authed(f,token,'/admin/accounts','POST',{username:'intruder',password:'password-123456',role:'owner'})).status,403);
  assert.equal((await authed(f,token,'/account/password','POST',{current_password:'wrong',new_password:'updated-password-123'})).status,401);
  assert.equal((await authed(f,token,'/account/password','POST',{current_password:loginPassword,new_password:'updated-password-123'})).status,200);
  assert.equal((await authed(f,token,'/account')).status,401);
  assert.equal((await f.handler(loginRequest('updated-password-123'))).status,200);
});
test('owner list never exposes password verifiers; legacy token does not grant account management',async()=>{
  const f=fixture(ownerEnv),token=(await (await f.handler(loginRequest())).json()).access_token;
  const result=await authed(f,token,'/admin/accounts');
  assert.equal(result.status,200);
  assert.equal((await result.text()).includes('password_hash'),false);
  assert.equal((await authed(f,env.RI_FEEDBACK_ADMIN_TOKEN,'/admin/accounts')).status,401);
});
