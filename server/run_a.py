"""Start the protected A API and its worker using persistent local configuration."""

import os
from pathlib import Path


def prepare_database_url(value: str | None = None) -> str:
    """Seed a new local A database before importing its shared session factory."""
    from sqlalchemy.engine import make_url
    from app.paths import project_path

    default=Path(__file__).resolve().parent/'.local'/'a-demo.db'
    url=make_url(value or 'sqlite:///'+str(default))
    if url.drivername.startswith('sqlite') and url.database not in (None,'',':memory:'):
        target=project_path(url.database).resolve()
        if not target.exists():
            from app.demo import create_demo
            create_demo(target)
        url=url.set(database=str(target))
    return url.render_as_string(hide_password=False)


def main():
    from server.configuration.settings import Settings
    settings = Settings.from_env()
    if not settings.a_admin_token:
        raise SystemExit('请先配置 server/.env 的 A_ADMIN_TOKEN；本入口不启用A免鉴权模式。')
    os.environ['LOCAL_DEMO'] = '0'
    os.environ['ADMIN_TOKEN'] = settings.a_admin_token
    os.environ['DATABASE_URL'] = prepare_database_url(os.getenv('D_A_DATABASE_URL'))
    from app.db import seed_sources
    import uvicorn
    seed_sources()
    print('A数据服务已启动：http://127.0.0.1:8000；数据库位于server/.local。')
    import subprocess, sys
    worker = subprocess.Popen([sys.executable, '-m', 'app.worker'], env=os.environ.copy())
    try:
        uvicorn.run('app.api:app', host='127.0.0.1', port=8000)
    finally:
        worker.terminate()
        worker.wait(timeout=10)


if __name__ == '__main__':
    main()
