from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import secrets
import time

from fastapi import HTTPException, Request
from pwdlib import PasswordHash

from server.configuration.settings import Settings
from server.domain.users import UserAlreadyExists, UserStore, UserStoreInvalid


@dataclass
class Session:
    username: str
    role: str
    display_name: str
    csrf: str
    expires: float
    user_id: str | None = None
    feedback_token: str | None = None
    cloud_feedback_token: str | None = None
    cloud_feedback_expires: int = 0
    cloud_feedback_role: str | None = None
    cloud_feedback_username: str | None = None


class AuthService:
    """D 的单进程本地会话；Cookie 只携带随机会话 ID。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.hasher = PasswordHash.recommended()
        self.password_hash = self.hasher.hash(settings.password)
        default_users = Path(__file__).resolve().parents[1] / '.local' / 'users.json'
        self.users = UserStore(settings.user_store or default_users)
        self.sessions: dict[str, Session] = {}
        self.failures: dict[str, list[float]] = defaultdict(list)

    def _prune(self):
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}
        for key in list(self.failures):
            self.failures[key] = [value for value in self.failures[key] if value > now - 60]
            if not self.failures[key]:
                self.failures.pop(key, None)

    def _client(self, request: Request):
        return request.client.host if request.client else 'local'

    def _check_rate_limit(self, request: Request):
        self._prune()
        client = self._client(request)
        if len(self.failures.get(client, [])) >= 5:
            raise HTTPException(429, '登录尝试过于频繁，请在一分钟后重试。')
        return client

    def _start(self, request: Request, *, username: str, role: str, display_name: str,
               user_id: str | None = None, feedback_token: str | None = None):
        client = self._client(request)
        old_sid = request.session.get('sid')
        if isinstance(old_sid, str):
            self.sessions.pop(old_sid, None)
        sid = secrets.token_urlsafe(32)
        session = Session(username, role, display_name, secrets.token_urlsafe(32),
                          time.time() + self.settings.ttl, user_id, feedback_token)
        self.sessions[sid] = session
        self.failures.pop(client, None)
        request.session.clear()
        request.session['sid'] = sid
        return session

    def login(self, request: Request, username: str, password: str):
        """Compatibility wrapper for the existing administrator login."""
        return self.login_admin(request, username, password)

    def login_admin(self, request: Request, username: str, password: str, cloud_auth=None):
        client = self._check_rate_limit(request)
        valid_user = secrets.compare_digest(username.encode(), self.settings.username.encode())
        local_valid = valid_user and self.hasher.verify(password, self.password_hash)
        cloud_session = None
        if cloud_auth:
            try:
                cloud_session = cloud_auth(username, password)
            except ValueError as exc:
                # An unavailable identity service is not a rejected password.
                # Keep the local administrator fallback usable while offline.
                if not local_valid and getattr(exc, 'status', 401) != 401:
                    status = 429 if getattr(exc, 'status', None) == 429 else 503
                    message = ('登录请求过于频繁，请稍后再试。' if status == 429 else
                               '团队登录服务暂时未响应，请稍后重试；这不表示账号或密码错误。')
                    raise HTTPException(status, message) from None
        if not (local_valid or cloud_session):
            self.failures[client].append(time.time())
            raise HTTPException(401, '账号或密码不正确。')
        session = self._start(request, username=username, role='admin', display_name=username)
        if cloud_session:
            session.cloud_feedback_token, session.cloud_feedback_expires = cloud_session[:2]
            session.cloud_feedback_role = cloud_session[2] if len(cloud_session)>2 else 'admin'
            session.cloud_feedback_username = cloud_session[3] if len(cloud_session)>3 else username
        return session

    def login_user(self, request: Request, username: str, password: str):
        client = self._check_rate_limit(request)
        try:
            user = self.users.authenticate(username, password)
        except UserStoreInvalid as exc:
            raise HTTPException(503, str(exc)) from exc
        if user is None:
            self.failures[client].append(time.time())
            raise HTTPException(401, '账号或密码不正确。')
        return self._start(request, username=user['username'], role='user', display_name=user['display_name'],
                           user_id=user['id'], feedback_token=user['feedback_token'])

    def register_user(self, request: Request, username: str, password: str, display_name: str):
        if username.strip().casefold() == self.settings.username.casefold():
            raise HTTPException(409, '该用户名不可注册。')
        try:
            user = self.users.register(username, password, display_name)
        except UserAlreadyExists as exc:
            raise HTTPException(409, str(exc)) from exc
        except UserStoreInvalid as exc:
            raise HTTPException(503, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return self._start(request, username=user['username'], role='user', display_name=user['display_name'],
                           user_id=user['id'], feedback_token=user['feedback_token'])

    def current(self, request: Request):
        sid = request.session.get('sid')
        session = self.sessions.get(sid) if isinstance(sid, str) else None
        if not session or session.expires <= time.time():
            if isinstance(sid, str):
                self.sessions.pop(sid, None)
            request.session.clear()
            raise HTTPException(401, '请先登录。')
        return session

    def logout(self, request: Request):
        sid = request.session.get('sid')
        if isinstance(sid, str):
            self.sessions.pop(sid, None)
        request.session.clear()


def require_authenticated(request: Request) -> Session:
    return request.app.state.auth.current(request)


def require_admin(request: Request) -> Session:
    session = require_authenticated(request)
    if session.role != 'admin':
        raise HTTPException(403, '该功能需要管理员权限。')
    return session


def require_session_write(request: Request) -> Session:
    session = require_authenticated(request)
    token = request.headers.get('x-csrf-token', '')
    if not secrets.compare_digest(token.encode(), session.csrf.encode()):
        raise HTTPException(403, '请求校验失败，请刷新登录状态后重试。')
    return session


def require_admin_write(request: Request) -> Session:
    session = require_session_write(request)
    if session.role != 'admin':
        raise HTTPException(403, '该功能需要管理员权限。')
    return session
