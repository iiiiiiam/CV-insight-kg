from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    page_size: Mapped[int] = mapped_column(Integer, default=100)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    venue: Mapped[str] = mapped_column(String(20), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(20), default="dblp", server_default="dblp")
    kind: Mapped[str] = mapped_column(String(20), default="refresh", server_default="refresh")
    dataset_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    active_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    attempted: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    events: Mapped[list[JobEvent]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    job: Mapped[Job] = relationship(back_populates="events")


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True)
    doi: Mapped[str | None] = mapped_column(String(255), unique=True)
    dblp_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    openalex_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(1000))
    title_normalized: Mapped[str] = mapped_column(String(1000))
    year: Mapped[int] = mapped_column(Integer)
    venue: Mapped[str] = mapped_column(String(20))
    authors_json: Mapped[str] = mapped_column(Text, default="[]")
    abstract: Mapped[str | None] = mapped_column(Text)
    cited_by_count: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (Index("ix_papers_venue_year", "venue", "year"),)


class PaperSource(Base):
    __tablename__ = "paper_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    raw_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_record"),)


class PaperBatch(Base):
    """A paper can appear in multiple import batches without being duplicated."""
    __tablename__ = "paper_batches"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), primary_key=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def database(url: str):
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    if "source" not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE jobs ADD COLUMN source VARCHAR(20) NOT NULL DEFAULT 'dblp'"))
                connection.execute(text("UPDATE jobs SET source='openalex' WHERE id IN "
                                        "(SELECT job_id FROM job_events WHERE message LIKE 'Imported %')"))
        except Exception:
            # API and worker can start together; another process may have added the column.
            if "source" not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
                raise
    for name, definition in (("kind", "VARCHAR(20) NOT NULL DEFAULT 'refresh'"), ("dataset_id", "VARCHAR(100) NULL")):
        if name not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
            try:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {definition}"))
            except Exception:
                if name not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
                    raise
    return sessionmaker(engine, expire_on_commit=False)
