from collections import defaultdict
from dataclasses import dataclass
import secrets
import time

from fastapi import HTTPException, Request
from pwdlib import PasswordHash

from server.configuration.settings import Settings


@dataclass
class Session:
    username: str
    csrf: str
    expires: float


class AuthService:
    """D 的单进程本地会话；Cookie 只携带随机会话 ID。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.hasher = PasswordHash.recommended()
        self.password_hash = self.hasher.hash(settings.password)
        self.sessions: dict[str, Session] = {}
        self.failures: dict[str, list[float]] = defaultdict(list)

    def _prune(self):
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires > now}
        for key in list(self.failures):
            self.failures[key] = [value for value in self.failures[key] if value > now - 60]
            if not self.failures[key]:
                self.failures.pop(key, None)

    def login(self, request: Request, username: str, password: str):
        self._prune()
        client = request.client.host if request.client else 'local'
        if len(self.failures.get(client, [])) >= 5:
            raise HTTPException(429, '登录尝试过于频繁，请在一分钟后重试。')
        valid_user = secrets.compare_digest(username.encode(), self.settings.username.encode())
        if not (valid_user and self.hasher.verify(password, self.password_hash)):
            self.failures[client].append(time.time())
            raise HTTPException(401, '账号或密码不正确。')

        old_sid = request.session.get('sid')
        if isinstance(old_sid, str):
            self.sessions.pop(old_sid, None)
        sid = secrets.token_urlsafe(32)
        session = Session(username, secrets.token_urlsafe(32), time.time() + self.settings.ttl)
        self.sessions[sid] = session
        self.failures.pop(client, None)
        request.session.clear()
        request.session['sid'] = sid
        return session

    def current(self, request: Request):
        sid = request.session.get('sid')
        session = self.sessions.get(sid) if isinstance(sid, str) else None
        if not session or session.expires <= time.time():
            if isinstance(sid, str):
                self.sessions.pop(sid, None)
            request.session.clear()
            raise HTTPException(401, '请先登录管理员账号。')
        return session

    def logout(self, request: Request):
        sid = request.session.get('sid')
        if isinstance(sid, str):
            self.sessions.pop(sid, None)
        request.session.clear()


def require_admin(request: Request) -> Session:
    return request.app.state.auth.current(request)


def require_admin_write(request: Request) -> Session:
    session = require_admin(request)
    token = request.headers.get('x-csrf-token', '')
    if not secrets.compare_digest(token.encode(), session.csrf.encode()):
        raise HTTPException(403, '请求校验失败，请刷新登录状态后重试。')
    return session
