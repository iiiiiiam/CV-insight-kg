'use strict';

const http = require('node:http');
const { createHash, timingSafeEqual } = require('node:crypto');
const { createTeamAccounts } = require('./accounts');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TOKEN = /^[0-9a-f]{64}$/;
const BODY_LIMIT = 4096;
const PUBLIC_FIELDS = 'id,status,processing_note,state_revision,created_at,updated_at';
const PRIVATE_FIELDS = `${PUBLIC_FIELDS},installation_id,local_feedback_id,receipt_token_hash,payload`;

class ApiError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
function requireValue(condition, status, code) {
  if (!condition) throw new ApiError(status, code);
}
function equalSecret(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  return timingSafeEqual(createHash('sha256').update(a).digest(), createHash('sha256').update(b).digest());
}
function digest(token) { return createHash('sha256').update(token).digest('hex'); }
function object(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function samePayload(a, b) {
  const canonical = value => JSON.stringify(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)));
  return object(a) && object(b) && canonical(a) === canonical(b);
}
function publicRecord(row) {
  return Object.fromEntries(PUBLIC_FIELDS.split(',').map(key => [key, row[key]]));
}
function json(status, value) {
  return new Response(JSON.stringify(value), {
    status, headers: {
      'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store',
      'x-content-type-options': 'nosniff',
    },
  });
}
async function readJson(request) {
  requireValue((request.headers.get('content-type') || '').split(';')[0].trim() === 'application/json',
    415, 'JSON_REQUIRED');
  const reader = request.body?.getReader();
  requireValue(reader, 400, 'BODY_REQUIRED');
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > BODY_LIMIT) { await reader.cancel(); throw new ApiError(413, 'BODY_TOO_LARGE'); }
      chunks.push(Buffer.from(value));
    }
    let result;
    try { result = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { throw new ApiError(400, 'INVALID_JSON'); }
    requireValue(object(result), 400, 'OBJECT_REQUIRED');
    return result;
  } finally { reader.releaseLock(); }
}
function submission(body) {
  const keys = ['installation_id', 'local_feedback_id', 'receipt_token', 'payload'];
  requireValue(Object.keys(body).every(key => keys.includes(key)), 400, 'UNKNOWN_FIELD');
  requireValue(typeof body.installation_id === 'string' && UUID.test(body.installation_id), 400, 'INVALID_INSTALLATION');
  requireValue(typeof body.local_feedback_id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(body.local_feedback_id),
    400, 'INVALID_LOCAL_ID');
  requireValue(typeof body.receipt_token === 'string' && TOKEN.test(body.receipt_token), 400, 'INVALID_RECEIPT');
  const payload = body.payload;
  const limits = { message: 1000, paper_id: 300, candidate_id: 200, knowledge_revision: 128,
    category: 64, display_name: 200 };
  requireValue(object(payload) && Object.keys(payload).every(key => Object.hasOwn(limits, key)), 400, 'INVALID_PAYLOAD');
  requireValue(typeof payload.message === 'string' && payload.message.trim(), 400, 'MESSAGE_REQUIRED');
  for (const [key, value] of Object.entries(payload)) {
    requireValue(typeof value === 'string' && value.length <= limits[key], 400, 'INVALID_PAYLOAD');
  }
  requireValue(Buffer.byteLength(JSON.stringify(payload), 'utf8') <= 2048, 413, 'PAYLOAD_TOO_LARGE');
  return { installation_id: body.installation_id.toLowerCase(), local_feedback_id: body.local_feedback_id,
    receipt_token_hash: digest(body.receipt_token), payload };
}

// Importing this module never starts a service or contacts the cloud.
function createHandler({ env = process.env, fetchImpl = globalThis.fetch, clock = () => new Date() } = {}) {
  const apiKey = env.CLOUDBASE_APIKEY || '';
  const envId = env.CLOUDBASE_ENV_ID || '';
  const pilotToken = env.RI_FEEDBACK_PILOT_TOKEN || '';
  const adminToken = env.RI_FEEDBACK_ADMIN_TOKEN || '';
  const publicEnabled = env.RI_FEEDBACK_PUBLIC_ENABLED === 'true';
  const signingKey = env.RI_FEEDBACK_SESSION_SECRET || adminToken;
  const loginWindow = { start: 0, count: 0 };
  const publicWindow = { start: 0, count: 0 };
  const databaseConfigured = Boolean(apiKey && /^[a-z0-9-]+$/.test(envId));
  const pilotConfigured = TOKEN.test(pilotToken) && !equalSecret(pilotToken, apiKey);
  const adminConfigured = TOKEN.test(adminToken) && !equalSecret(adminToken, pilotToken) && !equalSecret(adminToken, apiKey);
  const base = `https://${envId}.api.tcloudbasegateway.com/v1/rdb/rest/ri_feedback_requests`;

  async function database(method, query, data, prefer, resource='ri_feedback_requests', scalar=false) {
    requireValue(databaseConfigured, 503, 'DATABASE_NOT_CONFIGURED');
    try {
      const response = await fetchImpl(`${base.replace(/ri_feedback_requests$/,resource)}?${new URLSearchParams(query)}`, {
        method, redirect: 'error', signal: AbortSignal.timeout(1100),
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json',
          ...(prefer ? { Prefer: prefer } : {}) },
        ...(data === undefined ? {} : { body: JSON.stringify(data) }),
      });
      // Never return raw database errors or authorization headers to callers/logs.
      requireValue(response.ok, 503, 'DATABASE_UNAVAILABLE');
      const rows = await response.json();
      requireValue(scalar ? object(rows) : Array.isArray(rows), 503, 'DATABASE_UNAVAILABLE');
      return rows;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(503, 'DATABASE_UNAVAILABLE');
    }
  }
  function authorizePilot(request) {
    if (publicEnabled) return;
    requireValue(pilotConfigured, 503, 'PILOT_NOT_CONFIGURED');
    requireValue(equalSecret(request.headers.get('x-ri-pilot-token'), pilotToken), 401, 'UNAUTHORIZED');
  }
  const accounts = createTeamAccounts({database,readJson,json,clock,signingKey,
    legacyToken:adminToken,legacyEnabled:adminConfigured,requireValue,equalSecret,digest});
  function limit(window, maximum) {
    const now = clock().getTime();
    if (now - window.start >= 60000) { window.start = now; window.count = 0; }
    requireValue(++window.count <= maximum, 429, 'RATE_LIMITED');
  }
  return async function handle(request) {
    try {
      const url = new URL(request.url);
      const path = url.pathname.replace(/\/$/, '') || '/';
      requireValue(!url.search, 400, 'QUERY_NOT_SUPPORTED');
      if (request.method === 'GET' && (path === '/' || path === '/health')) {
        return json(200, { service: 'ri-feedback-api', version: '0.3.0', status: 'ok',
          database_configured: databaseConfigured, pilot_configured: pilotConfigured,
          admin_configured: adminConfigured || signingKey.length >= 32,
          public_enabled: publicEnabled }); // Readiness only; no database query.
      }
      if (request.method === 'POST' && path === '/sessions') {
        limit(loginWindow, 12);
        return await accounts.login(request);
      }
      if (path === '/account' || path === '/account/password' || path === '/admin/accounts'
          || path.startsWith('/admin/accounts/')) return await accounts.route(request,path);
      if (request.method === 'POST' && path === '/requests') {
        authorizePilot(request);
        if (publicEnabled) limit(publicWindow, 10);
        const row = submission(await readJson(request));
        let rows = await database('POST', { on_conflict: 'installation_id,local_feedback_id', select: PRIVATE_FIELDS },
          row, 'resolution=ignore-duplicates,return=representation');
        const created = rows.length === 1;
        if (!created) rows = await database('GET', { select: PRIVATE_FIELDS,
          installation_id: `eq.${row.installation_id}`, local_feedback_id: `eq.${row.local_feedback_id}`, limit: '1' });
        requireValue(rows.length === 1, 503, 'DATABASE_UNAVAILABLE');
        requireValue(equalSecret(rows[0].receipt_token_hash, row.receipt_token_hash)
          && samePayload(rows[0].payload, row.payload), 409, 'SUBMISSION_CONFLICT');
        return json(created ? 201 : 200, { feedback: publicRecord(rows[0]), duplicate: !created });
      }
      const ownerMatch = path.match(/^\/requests\/([0-9a-f-]+)$/i);
      if (request.method === 'GET' && ownerMatch) {
        authorizePilot(request);
        if (publicEnabled) limit(publicWindow, 30);
        requireValue(UUID.test(ownerMatch[1]), 400, 'INVALID_ID');
        const token = (request.headers.get('authorization') || '').replace(/^Bearer /, '');
        requireValue(TOKEN.test(token), 401, 'UNAUTHORIZED');
        const rows = await database('GET', { select: PRIVATE_FIELDS, id: `eq.${ownerMatch[1].toLowerCase()}`, limit: '1' });
        requireValue(rows.length === 1 && equalSecret(rows[0].receipt_token_hash, digest(token)), 404, 'NOT_FOUND');
        return json(200, { feedback: publicRecord(rows[0]) });
      }
      if (request.method === 'GET' && path === '/admin/requests') {
        await accounts.authorize(request);
        const rows = await database('GET', { select: `${PUBLIC_FIELDS},payload`, order: 'created_at.desc', limit: '20' });
        return json(200, { feedback: rows.map(row => ({ ...publicRecord(row), payload: row.payload })) });
      }
      const adminMatch = path.match(/^\/admin\/requests\/([0-9a-f-]+)$/i);
      if (request.method === 'PATCH' && adminMatch) {
        await accounts.authorize(request);
        requireValue(UUID.test(adminMatch[1]), 400, 'INVALID_ID');
        const body = await readJson(request);
        requireValue(Object.keys(body).every(key => ['status', 'processing_note', 'expected_revision'].includes(key)),
          400, 'UNKNOWN_FIELD');
        requireValue(['open', 'resolved', 'dismissed'].includes(body.status), 400, 'INVALID_STATUS');
        requireValue(typeof body.processing_note === 'string' && body.processing_note.trim()
          && body.processing_note.length <= 2000, 400, 'NOTE_REQUIRED');
        requireValue(Number.isSafeInteger(body.expected_revision) && body.expected_revision >= 0
          && body.expected_revision < Number.MAX_SAFE_INTEGER, 400, 'INVALID_REVISION');
        const rows = await database('PATCH', { id: `eq.${adminMatch[1].toLowerCase()}`,
          state_revision: `eq.${body.expected_revision}`, status: 'neq.withdrawn', select: PUBLIC_FIELDS },
        { status: body.status, processing_note: body.processing_note,
          state_revision: body.expected_revision + 1, updated_at: clock().toISOString() }, 'return=representation');
        requireValue(rows.length === 1, 409, 'STATE_CONFLICT');
        return json(200, { feedback: publicRecord(rows[0]) });
      }
      throw new ApiError(404, 'NOT_FOUND');
    } catch (error) {
      return json(error instanceof ApiError ? error.status : 500,
        { error: error instanceof ApiError ? error.code : 'INTERNAL_ERROR' });
    }
  };
}

function start() {
  const handler = createHandler();
  const server = http.createServer({ requestTimeout: 2500, headersTimeout: 2500 }, async (req, res) => {
    try {
      const chunks = [];
      let size = 0;
      req.setTimeout(2500, () => req.destroy());
      for await (const chunk of req) {
        size += chunk.length;
        if (size > BODY_LIMIT) {
          res.writeHead(413, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
          res.end('{"error":"BODY_TOO_LARGE"}');
          return;
        }
        chunks.push(chunk);
      }
      const request = new Request(`http://localhost${req.url}`, { method: req.method, headers: req.headers,
        ...(['GET', 'HEAD'].includes(req.method) ? {} : { body: Buffer.concat(chunks) }) });
      const response = await handler(request);
      res.writeHead(response.status, Object.fromEntries(response.headers));
      res.end(await response.text());
    } catch {
      if (!res.headersSent) res.writeHead(400, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
      res.end('{"error":"INVALID_REQUEST"}');
    }
  });
  server.keepAliveTimeout = 1000;
  server.listen(Number(process.env.PORT || 9000), '0.0.0.0', () => console.log('ri-feedback-api listening'));
  return server;
}

module.exports = { createHandler, start };
if (require.main === module) start();
