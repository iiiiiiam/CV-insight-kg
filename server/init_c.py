"""Explicit C setup: append missing D gateway values, preserve all existing values."""

from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent


def initialize():
    path = ROOT / '.env'
    if not path.exists():
        from server.init_local import initialize as initialize_d
        initialize_d()
    text = path.read_text(encoding='utf-8')
    values = dict(line.split('=', 1) for line in text.splitlines() if line and not line.lstrip().startswith('#') and '=' in line)
    changed = False
    for key, value in [('C_API_BASE_URL', 'http://127.0.0.1:8002'), ('C_ADMIN_TOKEN', secrets.token_urlsafe(32))]:
        if not values.get(key, '').strip():
            lines = [line for line in text.splitlines() if not line.startswith(key + '=')]
            text = '\n'.join(lines) + '\n' + key + '=' + value + '\n'
            changed = True
    if changed:
        path.write_text(text, encoding='utf-8')
    print('C 网关配置已就绪；保留原有账号与非空配置，不输出服务令牌。')


if __name__ == '__main__':
    initialize()
