"""Launch unchanged C API on port 8002. Neo4j credentials stay in local env."""

import os
from pathlib import Path
from dotenv import load_dotenv


def main():
    from server.configuration.settings import Settings
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / 'graph.env', override=False)
    load_dotenv(root / '.env', override=False)
    settings = Settings.from_env()
    if not settings.c_admin_token:
        raise SystemExit('请先运行 python -m server.init_c，或配置 C_ADMIN_TOKEN。')
    if not os.getenv('NEO4J_PASSWORD'):
        raise SystemExit('请先在本终端设置 NEO4J_PASSWORD，或在本地 graph.env 中配置 Neo4j。')
    os.environ['GRAPH_ADMIN_TOKEN'] = settings.c_admin_token
    import uvicorn
    uvicorn.run('src.graph_query.api:app', host='127.0.0.1', port=8002)


if __name__ == '__main__':
    main()
