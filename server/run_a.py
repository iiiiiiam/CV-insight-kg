"""Start unchanged A code in its existing protected mode, with an isolated demo DB."""

import os
from pathlib import Path


def main():
    from server.configuration.settings import Settings
    settings = Settings.from_env()
    if not settings.a_admin_token:
        raise SystemExit('请先配置 server/.env 的 A_ADMIN_TOKEN；本入口不启用A免鉴权模式。')
    local = Path(__file__).resolve().parent / '.local'
    local.mkdir(exist_ok=True)
    os.environ['LOCAL_DEMO'] = '0'
    os.environ['ADMIN_TOKEN'] = settings.a_admin_token
    os.environ['DATABASE_URL'] = os.getenv('D_A_DATABASE_URL', 'sqlite:///' + str(local / 'a-demo.db'))
    from app.db import SessionLocal, seed_sources
    from app.datasets import DATASET_ID, import_sample
    from app.models import Job
    from sqlalchemy import select
    import uvicorn
    seed_sources()
    with SessionLocal() as db:
        if db.scalar(select(Job).where(Job.dataset_id == DATASET_ID, Job.status == 'succeeded')) is None:
            result = import_sample(db)
            if result.status != 'succeeded':
                raise SystemExit('A样本导入未成功，请检查本地数据库和样本清单。')
    print('A原代码以既有受保护模式运行：http://127.0.0.1:8000；数据库位于server/.local。')
    uvicorn.run('app.api:app', host='127.0.0.1', port=8000)


if __name__ == '__main__':
    main()
