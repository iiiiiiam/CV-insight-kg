"""Create and verify A's tables in an explicitly provided, empty MySQL test database."""

import json
import os

from sqlalchemy import create_engine, func, inspect, select

from .datasets import import_sample
from .models import Job, Paper, PaperBatch, PaperSource, Source, database


def verify() -> dict:
    url = os.environ["WEEK1_TEST_DATABASE_URL"]
    engine = create_engine(url)
    if engine.dialect.name != "mysql" or not (engine.url.database or "").startswith("tupu_week1_check_"):
        raise ValueError("Use a dedicated MySQL database named tupu_week1_check_<suffix>")
    if inspect(engine).get_table_names():
        raise ValueError("The verification database must be empty")
    engine.dispose()
    factory = database(url)
    with factory() as db:
        db.add(Source(name="openalex"))
        db.commit()
        first = import_sample(db)
        first_ids = {p.openalex_id: p.id for p in db.scalars(select(Paper))}
        first_id = first.id
        second = import_sample(db)
        second_ids = {p.openalex_id: p.id for p in db.scalars(select(Paper))}
        counts = {"papers": db.scalar(select(func.count(Paper.id))),
                  "raw_records": db.scalar(select(func.count(PaperSource.id))),
                  "batches": db.scalar(select(func.count(Job.id))),
                  "batch_links": db.scalar(select(func.count()).select_from(PaperBatch))}
        if counts != {"papers": 20, "raw_records": 20, "batches": 2, "batch_links": 40} or first_ids != second_ids:
            raise RuntimeError("MySQL sample repeat verification failed")
        if not all(json.loads(source.raw_json).get("id") and source.retrieved_at
                   for source in db.scalars(select(PaperSource))):
            raise RuntimeError("MySQL raw record read/write verification failed")
        result = {"backend": "mysql", "tables_created_from_empty": True, **counts,
                  "batch_ids": [first_id, second.id], "stable_paper_ids": True, "raw_records_read_write": True}
    factory.kw["bind"].dispose()
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2))
