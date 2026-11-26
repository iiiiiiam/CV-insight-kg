"""Software-managed cloud delivery and team login, without end-user cloud keys or polling."""
import hashlib
from contextlib import contextmanager
import hmac
import json
from pathlib import Path
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid

from src.knowledge_builder.extraction import fingerprint


class CloudFeedbackError(ValueError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status=status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def send_request(method, url, headers, body, timeout=12):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
    try:
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            content = response.read(131073)
            if len(content) > 131072:
                raise CloudFeedbackError('云端响应过大。')
            return json.loads(content)
    except urllib.error.HTTPError as exc:
        try:
            code=json.loads(exc.read(4096)).get('error')
        except (ValueError,AttributeError):
            code=None
        if not isinstance(code,str):
            code=None
        account_errors={'ACCOUNT_EXISTS':'账号已存在，未覆盖原账号。',
                        'STATE_CONFLICT':'这条记录已被其他人修改，请刷新后再操作。',
                        'LAST_OWNER':'不能停用或降级最后一位账号管理员。',
                        'SELF_DISABLE':'不能停用自己或修改自己的管理角色。',
                        'FORBIDDEN':'当前账号没有此操作权限。',
                        'INVALID_PASSWORD':'密码长度应为 12–256 位。'}
        message = {401: '团队登录已失效或账号密码不正确，请重新登录。', 404: '云端记录不存在或凭证不匹配。',
                   409: '云端记录已变化，请重新查询后处理。', 413: '反馈过长，请联系维护者。'}.get(
                       exc.code, '云端暂不可用，本地记录保留，可稍后手动重试。')
        raise CloudFeedbackError(account_errors.get(code,message),
                                 exc.code if exc.code in (400,401,403,404,409,413,429) else 503) from None
    except (OSError, ValueError):
        raise CloudFeedbackError('云端请求未完成，本地记录保留；请手动查询或重试。') from None


class CloudFeedback:
    def __init__(self, settings, transport=None):
        self.url = getattr(settings, 'cloud_feedback_url', '').rstrip('/')
        self.pilot = getattr(settings, 'cloud_feedback_pilot_token', '')
        self.admin = getattr(settings, 'cloud_feedback_admin_token', '')
        self.path = getattr(settings, 'cloud_feedback_store', None)
        if not self.path:
            user_store = getattr(settings, 'user_store', None)
            reviews = getattr(settings, 'b_reviews_directory', None)
            directory = (Path(user_store).parent if user_store else Path(reviews) if reviews
                         else Path(__file__).resolve().parents[1] / '.local')
            self.path = str(directory / 'cloud-feedback.db')
        self.secret = settings.secret
        self.transport = transport or send_request

    @property
    def enabled(self):
        return bool(self.url)

    @contextmanager
    def connection(self):
        if not self.path:
            raise CloudFeedbackError('请配置独立的 CLOUD_FEEDBACK_STORE 数据文件路径。')
        path = Path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(path, timeout=3)
        con.row_factory = sqlite3.Row
        con.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL,
                cloud TEXT, service TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inbox (
                cloud_id TEXT PRIMARY KEY, document TEXT NOT NULL, local_id TEXT,
                service TEXT NOT NULL);
        ''')
        con.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', ('installation', str(uuid.uuid4())))
        con.commit()
        try:
            with con:
                yield con
        finally:
            con.close()

    def call(self, method, path, body=None, admin=False, receipt=None, session_token=None):
        parsed = urllib.parse.urlsplit(self.url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise CloudFeedbackError('云反馈地址必须是无凭证、无查询参数的 HTTPS 地址。')
        headers = {'Content-Type': 'application/json'}
        if admin:
            token = session_token or self.admin
            if not token:
                raise CloudFeedbackError('请使用团队管理员账号登录后处理团队反馈。')
            headers['Authorization'] = 'Bearer ' + token
        else:
            if self.pilot:
                headers['x-ri-pilot-token'] = self.pilot  # Legacy independent pilot only.
            if receipt:
                headers['Authorization'] = 'Bearer ' + receipt
        if path == '/sessions' and self.transport is send_request:
            result = self.transport(method, self.url + path, headers, body, timeout=3)
        else:
            result = self.transport(method, self.url + path, headers, body)
        if not isinstance(result, dict):
            raise CloudFeedbackError('云服务响应无效，本地功能仍可使用。')
        return result

    def login(self, username, password):
        result = self.call('POST', '/sessions', {'username': username, 'password': password})
        token, expiry = result.get('access_token'), result.get('expires_at')
        if (result.get('role') not in ('admin', 'owner') or not isinstance(token, str) or not token.startswith('ri1.')
                or type(expiry) is not int):
            raise CloudFeedbackError('团队登录响应无效。')
        return token, expiry, result['role'], result.get('username', username.strip().lower())

    def accounts(self, session_token):
        return self.call('GET', '/admin/accounts', admin=True, session_token=session_token)

    def add_account(self, body, session_token):
        return self.call('POST', '/admin/accounts', body, admin=True, session_token=session_token)

    def update_account(self, username, body, session_token):
        return self.call('PATCH', '/admin/accounts/' + urllib.parse.quote(username, safe=''), body,
                         admin=True, session_token=session_token)

    def change_password(self, body, session_token):
        return self.call('POST', '/account/password', body, admin=True, session_token=session_token)

    def completed_feedback_ids(self, owner):
        """Only trusted, locally cached cloud receipts owned by this submitter.

        No cloud read and no changes to local knowledge decisions.
        """
        if not self.enabled or not owner:
            return set()
        with self.connection() as con:
            rows=con.execute('SELECT id,cloud FROM outbox WHERE owner=? AND service=? AND cloud IS NOT NULL',
                             (fingerprint(owner),self.url)).fetchall()
            return {row['id'] for row in rows
                    if self.validate(json.loads(row['cloud']))['status'] in ('resolved','dismissed','withdrawn')}

    def prepare(self, identifier, owner, payload):
        if not self.enabled or not owner:
            return
        # Immutable request persisted before network; no cloud access here.
        with self.connection() as con:
            con.execute('INSERT OR IGNORE INTO outbox VALUES (?, ?, ?, NULL, ?)',
                        (identifier, fingerprint(owner), json.dumps(payload, ensure_ascii=False), self.url))

    def owned(self, con, identifier, owner):
        row = con.execute('SELECT * FROM outbox WHERE id=?', (identifier,)).fetchone()
        if (not row or not owner or not hmac.compare_digest(row['owner'], fingerprint(owner))
                or row['service'] != self.url):
            raise LookupError('未找到当前用户的云反馈回执。')
        return row

    def cached(self, identifier, owner):
        if not self.enabled:
            return None
        with self.connection() as con:
            try:
                row = self.owned(con, identifier, owner)
            except LookupError:
                return None
            cloud = json.loads(row['cloud']) if row['cloud'] else None
            return {'delivery': 'sent' if cloud else 'pending', 'feedback': cloud}

    @staticmethod
    def validate(value):
        try:
            uuid.UUID(value['id'])
            if (value['status'] not in ('open', 'resolved', 'dismissed', 'withdrawn')
                    or type(value['state_revision']) is not int or value['state_revision'] < 0
                    or not isinstance(value['processing_note'], str)):
                raise ValueError()
            return {key: value[key] for key in ('id', 'status', 'processing_note', 'state_revision',
                                               'created_at', 'updated_at')}
        except (KeyError, TypeError, ValueError, AttributeError):
            raise CloudFeedbackError('云端反馈响应无效，本地记录保留。') from None

    def exchange(self, identifier, owner, operation):
        with self.connection() as con:
            row = self.owned(con, identifier, owner)
            installation = con.execute("SELECT value FROM meta WHERE key='installation'").fetchone()[0]
            previous = json.loads(row['cloud']) if row['cloud'] else None
            receipt = hmac.new(self.secret.encode(), f'{installation}:{identifier}'.encode(), hashlib.sha256).hexdigest()
            if operation == 'send':
                body = {'installation_id': installation, 'local_feedback_id': identifier,
                        'receipt_token': receipt, 'payload': json.loads(row['payload'])}
                if (len(body['payload']['message']) > 1000
                        or len(json.dumps(body['payload'], ensure_ascii=False).encode()) > 2048):
                    raise CloudFeedbackError('本地反馈已保存，但超过云端试用文字限制（说明 1000 字、总计 2048 字节），未发送。')
                result = self.call('POST', '/requests', body)
            else:
                if not previous:
                    raise CloudFeedbackError('尚未确认送达，请先发送原记录。')
                result = self.call('GET', '/requests/' + str(uuid.UUID(previous['id'])), receipt=receipt)
            current = self.validate(result.get('feedback'))
            if previous and previous['id'] != current['id']:
                raise CloudFeedbackError('返回编号不一致，本地回执未更新。')
            # Do not replace a newer cached reply with a delayed older response.
            latest = con.execute('SELECT cloud FROM outbox WHERE id=?', (identifier,)).fetchone()[0]
            if latest and json.loads(latest)['state_revision'] > current['state_revision']:
                current = json.loads(latest)
            con.execute('UPDATE outbox SET cloud=? WHERE id=?', (json.dumps(current), identifier))
        return {'delivery': 'sent', 'feedback': current}

    def queue(self, session_token=None):
        result = self.call('GET', '/admin/requests', admin=True, session_token=session_token)
        rows = result.get('feedback')
        if not isinstance(rows, list) or len(rows) > 20:
            raise CloudFeedbackError('云端列表响应无效。')
        return {'requests': [{**self.validate(row), 'payload': row.get('payload', {})} for row in rows]}

    def remember_team(self, rows):
        with self.connection() as con:
            for row in rows:
                con.execute('INSERT INTO inbox VALUES (?, ?, NULL, ?) ON CONFLICT(cloud_id) DO UPDATE '
                            'SET document=excluded.document WHERE inbox.service=excluded.service',
                            (row['id'], json.dumps(row), self.url))
                for local in con.execute('SELECT id,cloud FROM outbox WHERE service=? AND cloud IS NOT NULL',(self.url,)).fetchall():
                    previous=json.loads(local['cloud'])
                    if previous['id']==row['id'] and previous['state_revision']<=row['state_revision']:
                        con.execute('UPDATE outbox SET cloud=? WHERE id=?',(json.dumps(self.validate(row)),local['id']))

    def team_cache(self):
        if not self.enabled:
            return [],{}
        with self.connection() as con:
            rows=[{'document':json.loads(row['document']),'local_id':row['local_id']}
                  for row in con.execute('SELECT * FROM inbox WHERE service=?',(self.url,))]
            links={}
            for row in con.execute('SELECT * FROM outbox WHERE service=? AND cloud IS NOT NULL',(self.url,)):
                record=json.loads(row['cloud']);links[record['id']]=row['id']
                if not any(item['document']['id']==record['id'] for item in rows):
                    rows.append({'document':{**record,'payload':json.loads(row['payload'])},'local_id':row['id']})
            return rows,links

    def link_team(self, cloud_id, local_id):
        with self.connection() as con:
            con.execute('UPDATE inbox SET local_id=? WHERE cloud_id=? AND service=?',(local_id,cloud_id,self.url))

    def reply(self, identifier, status, note, revision, session_token=None):
        identifier = str(uuid.UUID(identifier))
        result = self.call('PATCH', '/admin/requests/' + identifier,
                           {'status': status, 'processing_note': note, 'expected_revision': revision},
                           admin=True, session_token=session_token)
        return self.validate(result.get('feedback'))
