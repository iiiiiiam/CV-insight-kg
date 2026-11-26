"""Manual cloud feedback console. Standard library only; importing never uses network."""
from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_URL = ('https://ri-feedback-test-d3esfokfbb4ed58-1539629210.'
               'ap-shanghai.app.tcloudbase.com/feedback')
TOKEN = re.compile(r'^[0-9a-f]{64}$')
STATES = {'open', 'resolved', 'dismissed', 'withdrawn'}


class FeedbackError(Exception):
    pass


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def secret(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise FeedbackError('凭证应为 64 位小写十六进制字符，请重新输入。')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward credentials to a redirected host.


def transport(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(65537)
            if len(raw) > 65536:
                raise FeedbackError('响应过大，请联系维护者。')
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        messages = {401: '凭证不正确。', 404: '记录不存在或查询凭证不匹配。',
                    409: '记录已变化或请求冲突，请先刷新，不要强行覆盖。',
                    413: '反馈内容过大，请缩短。', 503: '云服务暂不可用，记录已保留，可稍后手动重试。'}
        raise FeedbackError(messages.get(exc.code, f'请求未完成（HTTP {exc.code}），记录保留。')) from None
    except (OSError, ValueError):
        raise FeedbackError('网络超时或响应无效，记录保留；请稍后手动重试。') from None


def record(value):
    try:
        uuid.UUID(value['id'])
        valid = (value['status'] in STATES and isinstance(value['processing_note'], str)
                 and type(value['state_revision']) is int and value['state_revision'] >= 0)
        if not valid:
            raise ValueError()
        return {key: value[key] for key in ('id', 'status', 'processing_note', 'state_revision',
                                           'created_at', 'updated_at')}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise FeedbackError('云端返回记录不完整，本地原记录保留。') from None


class CloudClient:
    def __init__(self, base=DEFAULT_URL, send=transport):
        parsed = urllib.parse.urlsplit(base)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise FeedbackError('服务地址必须是无凭证、无查询参数的 HTTPS 地址。')
        self.base, self.send = base.rstrip('/'), send

    def call(self, method, path, token=None, pilot=None, body=None):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + secret(token)
        if pilot is not None:
            headers['x-ri-pilot-token'] = secret(pilot)
        return self.send(method, self.base + path, headers, None if body is None else encode(body))

    def submit(self, item, pilot):
        result = self.call('POST', '/requests', pilot=pilot, body=item['request'])
        return record(result.get('feedback'))

    def status(self, item, pilot):
        cloud_id = str(uuid.UUID(item['cloud']['id']))
        return record(self.call('GET', '/requests/' + cloud_id, pilot=pilot,
                                token=item['request']['receipt_token']).get('feedback'))

    def queue(self, admin):
        result = self.call('GET', '/admin/requests', token=admin)
        rows = result.get('feedback')
        if not isinstance(rows, list) or len(rows) > 20:
            raise FeedbackError('团队列表响应无效。')
        return [{**record(row), 'payload': row.get('payload', {})} for row in rows]

    def update(self, row, admin, status, note):
        if status not in {'open', 'resolved', 'dismissed'} or not note.strip() or len(note) > 2000:
            raise FeedbackError('请选择有效状态并填写 1–2000 字的处理说明。')
        identifier = str(uuid.UUID(row['id']))
        return record(self.call('PATCH', '/admin/requests/' + identifier, token=admin,
                                body={'status': status, 'processing_note': note,
                                      'expected_revision': row['state_revision']}).get('feedback'))


class WindowsProtection:
    """DPAPI binds the local file to the current Windows user, without a saved key."""
    @staticmethod
    def _apply(data, decrypt=False):
        if os.name != 'nt':
            raise FeedbackError('本地凭证存档当前仅支持 Windows。')
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

        buffer = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        target = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise FeedbackError('无法保护或读取存档，请使用创建存档的 Windows 账户。')
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))

    def protect(self, data):
        return self._apply(data)

    def unprotect(self, data):
        return self._apply(data, True)


class LocalStore:
    def __init__(self, directory, protection=None):
        self.directory = Path(directory)
        self.path = self.directory / 'feedback.dpapi'
        self.protection = protection or WindowsProtection()
        self.lock = self.directory / 'session.lock'
        self.data = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise FeedbackError('该目录正在使用；若上次异常退出，请确认工具已关闭再删除 session.lock。') from None
        os.close(descriptor)
        try:
            if self.path.exists():
                self.data = json.loads(self.protection.unprotect(self.path.read_bytes()))
                if (self.data.get('format') != 1 or not isinstance(self.data.get('items'), list)
                        or not isinstance(self.data.get('installation_id'), str)):
                    raise ValueError()
            else:
                self.data = {'format': 1, 'installation_id': str(uuid.uuid4()), 'items': []}
                self.save()
            return self
        except Exception:
            self.lock.unlink(missing_ok=True)
            raise FeedbackError('本地存档无法读取或保存，原文件未清空；请检查账户和目录。') from None

    def __exit__(self, *args):
        self.lock.unlink(missing_ok=True)

    def save(self):
        data = self.protection.protect(encode(self.data))
        descriptor, name = tempfile.mkstemp(prefix='feedback-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def bind_service(self, address):
        previous = self.data.get('service_url')
        if previous and previous != address:
            raise FeedbackError('该存档属于另一云环境，请为新环境指定不同的数据目录。')
        self.data['service_url'] = address
        self.save()

    def draft(self, message, paper_id=''):
        payload = {'message': message.strip()}
        if paper_id.strip():
            payload['paper_id'] = paper_id.strip()
        if not payload['message'] or len(payload['message']) > 1000 or len(paper_id) > 300 or len(encode(payload)) > 2048:
            raise FeedbackError('内容为空或过长：说明最多 1000 字、论文编号最多 300 字，总计最多 2048 字节。')
        item = {'request': {'installation_id': self.data['installation_id'],
                           'local_feedback_id': str(uuid.uuid4()),
                           'receipt_token': secrets.token_hex(32), 'payload': payload},
                'cloud': None}
        self.data['items'].append(item)
        self.save()  # Durable before any network operation, so retry uses the same identity.
        return item

    def send(self, client, item, pilot):
        result = client.submit(item, pilot)
        if item['cloud'] and result['id'] != item['cloud']['id']:
            raise FeedbackError('返回编号不一致，本地记录未更新。')
        item['cloud'] = result
        self.save()
        return result

    def refresh(self, client, item, pilot):
        if not item['cloud']:
            raise FeedbackError('尚未确认送达，请先发送/重试原记录。')
        result = client.status(item, pilot)
        if result['id'] != item['cloud']['id']:
            raise FeedbackError('返回编号不一致，本地记录未更新。')
        item['cloud'] = result
        self.save()
        return result


def show(row):
    print(f"编号：{row['id']}\n状态：{row['status']}（版本 {row['state_revision']}）")
    print('团队回复：' + (row['processing_note'] or '暂无'))


def choose(items):
    if not items:
        raise FeedbackError('没有可选择的记录。')
    value = input('输入上面列表的序号：').strip()
    if not value.isdigit() or not 1 <= int(value) <= len(items):
        raise FeedbackError('序号不正确。')
    return items[int(value) - 1]


def run(store, client):
    pilot = admin = None  # Session only; never persist shared access/admin credentials.
    while True:
        print('\n1 本地记录  2 新建反馈（仅本地）  3 发送/重试一条  4 查一条回复')
        print('5 团队列表/处理  6 重新输入凭证  0 退出')
        action = input('请选择：').strip()
        try:
            if action == '0':
                return
            if action == '6':
                pilot = admin = None
                print('已清除工具持有的会话凭证，下次操作重新输入。')
            elif action in {'1', '3', '4'}:
                items = store.data['items']
                for i, item in enumerate(items, 1):
                    state = item['cloud']['status'] if item['cloud'] else '未确认送达，可发送/重试'
                    print(f"{i}. [{state}] {item['request']['payload']['message']}")
                    if item['cloud']:
                        show(item['cloud'])
                if action == '1':
                    print('以上为本地缓存；仅选择“查一条回复”才访问云端。')
                    continue
                item = choose(items)
                pilot = pilot or secret(getpass.getpass('输入试用凭证（不显示）：'))
                print('本次只请求一条，不会自动重试。')
                result = store.send(client, item, pilot) if action == '3' else store.refresh(client, item, pilot)
                show(result)
            elif action == '2':
                message = input('反馈说明（必填）：')
                paper = input('论文编号/链接（可留空）：')
                store.draft(message, paper)
                print('已加密保存到本地，尚未发往云端。选择 3 才发送。')
            elif action == '5':
                admin = admin or secret(getpass.getpass('输入团队处理凭证（不显示）：'))
                rows = client.queue(admin)
                for i, row in enumerate(rows, 1):
                    print(f"\n{i}. {row['payload'].get('message', '')}")
                    print('论文：' + str(row['payload'].get('paper_id', '未提供')))
                    show(row)
                print('只展示最近 20 条。直接回车返回；输入 y 选择一条处理。')
                if input().strip().lower() != 'y':
                    continue
                row = choose(rows)
                state = input('状态（resolved 已处理 / dismissed 保留原状 / open 待处理）：').strip()
                note = input('给提交者的处理说明：')
                if input('确认保存？输入 y：').strip().lower() == 'y':
                    show(client.update(row, admin, state, note))
                    print('处理结果已保存。它不会自动修改本地知识图谱。')
            else:
                print('请输入菜单中的数字。')
        except FeedbackError as exc:
            print(str(exc))
            pilot = admin = None
        except (OSError, ValueError, KeyError, TypeError):
            print('操作未完成，请检查本地存档和输入；不要删除原记录。')


def main():
    parser = argparse.ArgumentParser(description='云反馈手动工具：不轮询、不自动重试。')
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).resolve().parent / 'local-data')
    parser.add_argument('--url', default=DEFAULT_URL)
    args = parser.parse_args()
    try:
        client = CloudClient(args.url)
        with LocalStore(args.data_dir) as store:
            store.bind_service(client.base)
            print('云反馈工具：提交、查回复、团队处理。启动和查看本地记录不联网。')
            print('存档目录：' + str(args.data_dir.resolve()))
            run(store, client)
    except (FeedbackError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\n已退出；已保存的本地记录保留。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
