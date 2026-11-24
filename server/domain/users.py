"""Persistent local user accounts for the D prototype."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import threading

from pwdlib import PasswordHash


FORMAT = "cvkg-users/1"


class UserStoreInvalid(RuntimeError):
    pass


class UserAlreadyExists(ValueError):
    pass


def _empty():
    return {"format_version": FORMAT, "users": []}


class UserStore:
    """Small, atomic JSON account store; password hashes never leave the server."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.lock = threading.RLock()
        self.hasher = PasswordHash.recommended()
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(24))

    def _read(self):
        if not self.path.exists():
            return _empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UserStoreInvalid("普通用户账号文件无法读取") from exc
        if not isinstance(data, dict) or data.get("format_version") != FORMAT or not isinstance(data.get("users"), list):
            raise UserStoreInvalid("普通用户账号文件格式不正确")
        required = {"id", "username", "username_key", "display_name", "password_hash", "feedback_token", "created_at", "active"}
        keys = set()
        for user in data["users"]:
            if not isinstance(user, dict) or not required <= set(user) or not isinstance(user["active"], bool):
                raise UserStoreInvalid("普通用户账号记录格式不正确")
            if not all(isinstance(user[key], str) and user[key] for key in required - {"active"}):
                raise UserStoreInvalid("普通用户账号记录缺少字段")
            if user["username_key"] in keys:
                raise UserStoreInvalid("普通用户账号文件存在重复账号")
            keys.add(user["username_key"])
        return data

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp-" + secrets.token_hex(6))
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def normalize_username(value: str):
        username = value.strip()
        if not 3 <= len(username) <= 50 or any(character.isspace() or ord(character) < 32 for character in username):
            raise ValueError("用户名应为3—50个不含空格的字符。")
        return username, username.casefold()

    @staticmethod
    def validate_password(value: str):
        if not 8 <= len(value) <= 128:
            raise ValueError("密码长度应为8—128位。")
        if not any(character.isalpha() for character in value) or not any(character.isdigit() for character in value):
            raise ValueError("密码至少需要包含一个字母和一个数字。")

    def register(self, username: str, password: str, display_name: str):
        username, key = self.normalize_username(username)
        display_name = display_name.strip()
        if not 1 <= len(display_name) <= 50:
            raise ValueError("显示名称应为1—50个字符。")
        self.validate_password(password)
        with self.lock:
            data = self._read()
            if any(user["username_key"] == key for user in data["users"]):
                raise UserAlreadyExists("该用户名已被注册。")
            user = {
                "id": "usr_" + secrets.token_hex(12),
                "username": username,
                "username_key": key,
                "display_name": display_name,
                "password_hash": self.hasher.hash(password),
                "feedback_token": secrets.token_hex(32),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "active": True,
            }
            data["users"].append(user)
            self._write(data)
            return deepcopy(user)

    def authenticate(self, username: str, password: str):
        try:
            _username, key = self.normalize_username(username)
        except ValueError:
            key = ""
        with self.lock:
            user = next((item for item in self._read()["users"] if item["username_key"] == key), None)
        password_hash = user["password_hash"] if user else self.dummy_hash
        valid = self.hasher.verify(password, password_hash)
        if not user or not valid or not user["active"]:
            return None
        return deepcopy(user)
