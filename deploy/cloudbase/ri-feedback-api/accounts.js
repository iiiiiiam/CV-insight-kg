'use strict';
const {createHmac,scryptSync,randomBytes} = require('node:crypto');
const NAME = /^[a-z][a-z0-9_.-]{2,49}$/;
const FIELDS = 'username,role,enabled,revision,created_at,updated_at';

// Account writes are serialized and permission/revision checked again by the SQL RPC.
function createTeamAccounts({database,readJson,json,clock,signingKey,legacyToken,legacyEnabled,
  requireValue,equalSecret,digest}) {
  const validName = name => typeof name === 'string' && NAME.test(name);
  async function find(username) {
    const rows = await database('GET', {username:`eq.${username}`,select:`${FIELDS},password_hash`,limit:'1'},
      undefined,undefined,'ri_team_accounts');
    return rows.length === 1 ? rows[0] : null;
  }
  function checkPassword(password,stored) {
    const match = /^scrypt\$([0-9a-f]{32})\$([0-9a-f]{64})$/.exec(stored || '');
    const result = scryptSync(password,match ? Buffer.from(match[1],'hex') : Buffer.alloc(16),32).toString('hex');
    return Boolean(match && equalSecret(result,match[2]));
  }
  function hashPassword(password) {
    requireValue(typeof password === 'string' && password.length >= 12 && password.length <= 256,400,'INVALID_PASSWORD');
    const salt=randomBytes(16);
    return `scrypt$${salt.toString('hex')}$${scryptSync(password,salt,32).toString('hex')}`;
  }
  function publicAccount(row) {return Object.fromEntries(FIELDS.split(',').map(key=>[key,row[key]]));}
  async function authorize(request,accountsOnly=false) {
    const value=request.headers.get('authorization') || '';
    if (!accountsOnly && legacyEnabled && equalSecret(value,`Bearer ${legacyToken}`)) return {legacy:true};
    requireValue(signingKey.length>=32,503,'ADMIN_NOT_CONFIGURED');
    const parts=value.replace(/^Bearer /,'').split('.');
    requireValue(parts.length===3&&parts[0]==='ri1',401,'UNAUTHORIZED');
    requireValue(equalSecret(createHmac('sha256',signingKey).update(parts[1]).digest('base64url'),parts[2]),401,'UNAUTHORIZED');
    let claims;
    try {claims=JSON.parse(Buffer.from(parts[1],'base64url').toString());} catch {requireValue(false,401,'UNAUTHORIZED');}
    requireValue(validName(claims?.sub)&&Number.isSafeInteger(claims.exp)&&claims.exp>Math.floor(clock().getTime()/1000),401,'UNAUTHORIZED');
    const user=await find(claims.sub);
    requireValue(user?.enabled&&['owner','admin'].includes(user.role)&&claims.role===user.role
      &&equalSecret(String(user.revision),claims.version),401,'UNAUTHORIZED');
    return user;
  }
  async function login(request) {
    requireValue(signingKey.length>=32,503,'ADMIN_NOT_CONFIGURED');
    const body=await readJson(request);
    requireValue(typeof body.username==='string'&&body.username.length<=100
      &&typeof body.password==='string'&&body.password.length>=1&&body.password.length<=256,400,'INVALID_LOGIN');
    const username=body.username.trim().toLowerCase();
    const user=validName(username)?await find(username):null;
    const correct=checkPassword(body.password,user?.password_hash);
    requireValue(correct&&user.enabled&&['owner','admin'].includes(user.role),401,'UNAUTHORIZED');
    const exp=Math.floor(clock().getTime()/1000)+3600;
    const payload=Buffer.from(JSON.stringify({sub:username,role:user.role,exp,version:String(user.revision),
      nonce:randomBytes(12).toString('hex')})).toString('base64url');
    const signature=createHmac('sha256',signingKey).update(payload).digest('base64url');
    return json(200,{access_token:`ri1.${payload}.${signature}`,expires_at:exp,role:user.role,username});
  }
  async function mutate(actor,action,username,body) {
    const result=await database('POST',{}, {
      p_actor:actor.username,p_actor_revision:actor.revision,p_action:action,p_username:username,
      p_expected_revision:body.expected_revision??null,p_password_hash:body.password_hash??null,
      p_role:body.role??null,p_enabled:body.enabled??null,
    },undefined,'rpc/ri_team_manage',true);
    const statuses={FORBIDDEN:403,UNAUTHORIZED:401,ACCOUNT_EXISTS:409,STATE_CONFLICT:409,
      LAST_OWNER:409,SELF_DISABLE:409,NOT_FOUND:404,INVALID_INPUT:400};
    if(result.error){const known=Object.hasOwn(statuses,result.error);requireValue(false,known?statuses[result.error]:503,known?result.error:'DATABASE_UNAVAILABLE');}
    requireValue(result.account&&validName(result.account.username),503,'DATABASE_UNAVAILABLE');
    return json(200,{account:publicAccount(result.account)});
  }
  async function route(request,path) {
    const actor=await authorize(request,true);
    if(request.method==='GET'&&path==='/account')return json(200,{account:publicAccount(actor)});
    if(request.method==='POST'&&path==='/account/password') {
      const body=await readJson(request);
      requireValue(typeof body.current_password==='string'&&body.current_password.length<=256,400,'INVALID_PASSWORD');
      requireValue(checkPassword(body.current_password,actor.password_hash),401,'UNAUTHORIZED');
      return mutate(actor,'password',actor.username,{expected_revision:actor.revision,password_hash:hashPassword(body.new_password)});
    }
    requireValue(actor.role==='owner',403,'FORBIDDEN');
    if(request.method==='GET'&&path==='/admin/accounts') {
      const rows=await database('GET',{select:FIELDS,order:'username.asc',limit:'201'},undefined,undefined,'ri_team_accounts');
      requireValue(rows.length<=200,503,'ACCOUNT_LIMIT');
      return json(200,{accounts:rows.map(publicAccount),current_username:actor.username});
    }
    const body=await readJson(request);
    if(request.method==='POST'&&path==='/admin/accounts') {
      const username=typeof body.username==='string'?body.username.trim().toLowerCase():'';
      requireValue(validName(username)&&['owner','admin'].includes(body.role),400,'INVALID_ACCOUNT');
      return mutate(actor,'create',username,{role:body.role,enabled:true,password_hash:hashPassword(body.password)});
    }
    const match=path.match(/^\/admin\/accounts\/([a-z][a-z0-9_.-]{2,49})$/);
    requireValue(request.method==='PATCH'&&match,404,'NOT_FOUND');
    requireValue(Number.isSafeInteger(body.expected_revision)&&body.expected_revision>=0,400,'INVALID_REVISION');
    requireValue(Object.keys(body).every(key=>['expected_revision','role','enabled','new_password'].includes(key)),400,'UNKNOWN_FIELD');
    requireValue(body.role===undefined||['owner','admin'].includes(body.role),400,'INVALID_ROLE');
    requireValue(body.enabled===undefined||typeof body.enabled==='boolean',400,'INVALID_ACCOUNT');
    requireValue(body.role!==undefined||body.enabled!==undefined||body.new_password!==undefined,400,'EMPTY_UPDATE');
    const changes={...body};
    requireValue(match[1]!==actor.username||body.new_password===undefined,403,'FORBIDDEN');
    if(body.new_password!==undefined)changes.password_hash=hashPassword(body.new_password);
    return mutate(actor,'update',match[1],changes);
  }
  return {authorize,login,route};
}
module.exports={createTeamAccounts};
