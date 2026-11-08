from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    secret: str
    ttl: int = 3600
    cookie_secure: bool = False
    origins: tuple[str, ...] = ()
    a_base_url: str = 'http://127.0.0.1:8000'
    a_admin_token: str = ''
    b_vocabulary_path: str | None = None
    b_reviews_directory: str | None = None
    b_source_corpus: str | None = None
    c_base_url: str = 'http://127.0.0.1:8002'
    c_admin_token: str = ''

    @classmethod
    def from_env(cls):
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
        password = os.getenv('ADMIN_PASSWORD', '')
        secret = os.getenv('SESSION_SECRET', '')
        if len(password) < 12 or len(secret) < 32:
            raise RuntimeError('请先运行 python -m server.init_local，生成 server/.env 中的管理员凭据和会话密钥。')
        origins = os.getenv(
            'ALLOWED_ORIGINS',
            'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173,http://127.0.0.1:8001,http://localhost:8001',
        )
        return cls(
            username=os.getenv('ADMIN_USERNAME', 'admin'),
            password=password,
            secret=secret,
            ttl=max(60, int(os.getenv('SESSION_TTL_SECONDS', '3600'))),
            cookie_secure=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
            origins=tuple(item.strip().rstrip('/') for item in origins.split(',') if item.strip()),
            a_base_url=os.getenv('A_API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/'),
            a_admin_token=os.getenv('A_ADMIN_TOKEN', ''),
            c_base_url=os.getenv('C_API_BASE_URL', 'http://127.0.0.1:8002').rstrip('/'),
            c_admin_token=os.getenv('C_ADMIN_TOKEN') or os.getenv('GRAPH_ADMIN_TOKEN', ''),
            b_vocabulary_path=os.getenv('B_VOCABULARY_PATH') or None,
            b_source_corpus=os.getenv('B_SOURCE_CORPUS') or None,
            b_reviews_directory=(os.getenv('B_REVIEWS_DIR') or
                                 (str(Path(os.environ['KNOWLEDGE_WORKBENCH_DATA']) / 'reviews')
                                  if os.getenv('KNOWLEDGE_WORKBENCH_DATA') else None)),
        )
