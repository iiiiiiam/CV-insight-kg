"""Create D-only local settings; never overwrite A/B files or existing credentials."""

from pathlib import Path
import secrets


ROOT = Path(__file__).resolve().parent


def initialize():
    path = ROOT / '.env'
    if path.exists():
        print('D配置已存在，保留账号及密钥。')
        return
    text = (ROOT / '.env.example').read_text(encoding='utf-8')
    for key, length in [('ADMIN_PASSWORD', 18), ('SESSION_SECRET', 48), ('A_ADMIN_TOKEN', 32)]:
        text = text.replace(key + '=\n', key + '=' + secrets.token_urlsafe(length) + '\n')
    with path.open('x', encoding='utf-8') as file:
        file.write(text)
    print('已生成 server/.env；管理员账号admin，密码请在该本地文件中查看。')


if __name__ == '__main__':
    initialize()
