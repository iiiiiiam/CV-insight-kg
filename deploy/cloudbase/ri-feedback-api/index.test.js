'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHandler } = require('./index');
const env = { CLOUDBASE_ENV_ID: 'offline-test', CLOUDBASE_APIKEY: 'fake-server-key',
  RI_FEEDBACK_PILOT_TOKEN: 'a'.repeat(64), RI_FEEDBACK_ADMIN_TOKEN: 'b'.repeat(64) };
const id = '11111111-1111-4111-8111-111111111111';
const body = { installation_id: '22222222-2222-4222-8222-222222222222', local_feedback_id: 'local-1',
  receipt_token: 'c'.repeat(64), payload: { message: 'Please review this label.' } };
function fixture(customEnv = env) {
  let row;
  const calls = [];
  const handler = createHandler({ env: customEnv, clock: () => new Date('2026-11-26T00:00:00Z'),
    fetchImpl: async (address, options) => {
      const url = new URL(address);
      assert.equal(url.hostname, 'offline-test.api.tcloudbasegateway.com');
      assert.equal(options.headers.Authorization, 'Bearer fake-server-key');
      assert.equal(options.redirect, 'error');
      calls.push({ url, options });
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
  return { request, calls, handler, getRow: () => row };
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
