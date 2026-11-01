"""Shared database setup for the API, worker, and command line tools."""

import os

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import Source, database
from .paths import PROJECT_ROOT, project_path
from sqlalchemy.engine import make_url

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    if not os.getenv("DATABASE_URL"):
        raise
else:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
database_url = make_url(os.getenv("DATABASE_URL", "sqlite:///tupu.db"))
if database_url.drivername.startswith("sqlite") and database_url.database not in (None, "", ":memory:"):
    database_url = database_url.set(database=str(project_path(database_url.database)))
SessionLocal = database(database_url)


def seed_sources(session_factory=None):
    factory = session_factory or SessionLocal
    with factory() as db:
        for name in ("dblp", "openalex", "ecva"):
            if db.scalar(select(Source).where(Source.name == name)) is None:
                try:
                    with db.begin_nested():
                        db.add(Source(name=name))
                except IntegrityError:
                    pass  # Another service initialized this source at the same time.
        db.commit()
