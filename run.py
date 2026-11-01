"""Local entry point: initialize settings, load the real sample once, and start the API."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="启动第一周论文数据开发预览")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-reload", action="store_true")
    args = parser.parse_args()
    os.environ["LOCAL_DEMO"] = "1"
    root = Path(__file__).resolve().parent
    from scripts.init_project import initialize
    initialize(root)
    try:
        import uvicorn
        from sqlalchemy import select
        from app.db import SessionLocal, seed_sources
        from app.datasets import DATASET_ID, import_sample
        from app.models import Job
    except ModuleNotFoundError as exc:
        raise SystemExit("请先安装依赖：python -m pip install -r requirements-dev.txt") from exc
    seed_sources()
    with SessionLocal() as db:
        existing = db.scalar(select(Job).where(Job.dataset_id == DATASET_ID, Job.status == "succeeded"))
        if existing is None:
            job = import_sample(db, DATASET_ID)
            if job.status != "succeeded":
                raise SystemExit("样例导入未完成，请检查任务日志。")
            print(f"已导入 20 篇真实论文，批次 BATCH-{job.id:06d}。")
    print(f"论文预览：http://localhost:{args.port}/")
    print(f"导入管理：http://localhost:{args.port}/admin")
    uvicorn.run("app.api:app", host="127.0.0.1", port=args.port, reload=not args.no_reload,
                app_dir=str(root), reload_dirs=[str(root / "app")] if not args.no_reload else None)


if __name__ == "__main__":
    main()
