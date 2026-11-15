from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, inspect, text, event
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
    import_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    dataset_id: Mapped[str | None] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    active_key: Mapped[str | None] = mapped_column(String(40), unique=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    attempted: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    events: Mapped[list[JobEvent]] = relationship(back_populates="job", cascade="all, delete-orphan")


class CvfRecord(Base):
    __tablename__ = "cvf_job_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    __table_args__ = (UniqueConstraint("job_id", "source_id", name="uq_cvf_job_record"),)


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


class JobRecord(Base):
    """Frozen inputs and durable per-record checkpoints for a refresh batch."""
    __tablename__ = "job_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stage: Mapped[str] = mapped_column(String(40), default="upsert")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("job_id", "source", "source_id", name="uq_job_record"),)


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


class ImportCandidate(Base):
    """Verified supplementary metadata; not part of the imported paper collection."""
    __tablename__ = 'import_candidates'
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(255))
    venue: Mapped[str] = mapped_column(String(20))
    year: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(1000))
    title_normalized: Mapped[str] = mapped_column(String(1000))
    doi: Mapped[str | None] = mapped_column(String(255))
    payload_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    input_sha256: Mapped[str] = mapped_column(String(64))
    claimed_job_id: Mapped[int | None] = mapped_column(ForeignKey('jobs.id'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint('source','source_id',name='uq_import_candidate'), Index('ix_candidate_scope','venue','year','source','claimed_job_id'))


class SourceRevision(Base):
    __tablename__ = 'source_revisions'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_record_id: Mapped[int] = mapped_column(ForeignKey('paper_sources.id'), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint('source_record_id', 'fingerprint', name='uq_source_revision'),)


class PaperBatch(Base):
    """A paper can appear in multiple import batches without being duplicated."""
    __tablename__ = "paper_batches"
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), primary_key=True, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    # Null means this association predates tracking, so its creation status is unknown.
    is_new: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class BatchScopeLock(Base):
    __tablename__ = 'a_batch_scope_locks'
    scope_key: Mapped[str] = mapped_column(String(64), primary_key=True)


class BatchLedger(Base):
    """Immutable formal inputs with an explicit batch withdrawal state."""
    __tablename__ = 'a_batch_ledger'
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), primary_key=True)
    batch_key: Mapped[str] = mapped_column(String(180), unique=True)
    input_sha256: Mapped[str] = mapped_column(String(64))
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)


class StablePaper(Base):
    __tablename__ = 'a_stable_papers'
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'), primary_key=True)
    stable_id: Mapped[str] = mapped_column(String(255), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))


class BatchWithdrawalAudit(Base):
    """The effect of a withdrawal at execution time, independent of later imports."""
    __tablename__ = 'a_batch_withdrawal_audits'
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    removed_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    retained_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    reconstructed: Mapped[bool] = mapped_column(Boolean, default=False)


class BatchPaperVersion(Base):
    """The original paper text and evidence for each batch, never overwritten by another batch."""
    __tablename__ = 'a_batch_paper_versions'
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'), primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey('papers.id'), primary_key=True)
    change_kind: Mapped[str] = mapped_column(String(20))
    content_sha256: Mapped[str] = mapped_column(String(64))
    content_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))


def database(url: str):
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def foreign_keys(connection, _record):
            connection.execute('PRAGMA busy_timeout=30000')
            connection.execute('PRAGMA foreign_keys=ON')
    from .worker_lock import worker_lock
    import time
    factory=sessionmaker(engine,expire_on_commit=False)
    for attempt in range(300):
        try:
            with worker_lock(factory,role='schema'):
                _prepare_database(engine)
            return factory
        except (OSError,RuntimeError) as exc:
            import errno
            if isinstance(exc,OSError) and exc.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):raise
            if isinstance(exc,RuntimeError) and 'Another worker is already running' not in str(exc):raise
            if attempt==299:engine.dispose();raise
            time.sleep(.1)


def _prepare_database(engine):
    if engine.dialect.name=='sqlite' and engine.url.database not in (None,'',':memory:'):
        with engine.connect() as connection:connection.exec_driver_sql('PRAGMA journal_mode=WAL')
    from . import operations  # Register A receipt tables for API and worker alike.
    Base.metadata.create_all(engine)
    if "is_new" not in {column["name"] for column in inspect(engine).get_columns("paper_batches")}:
        try:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE paper_batches ADD COLUMN is_new BOOLEAN NULL"))
        except Exception:
            if "is_new" not in {column["name"] for column in inspect(engine).get_columns("paper_batches")}:
                raise
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
    for name, definition in (("skipped", "INTEGER NOT NULL DEFAULT 0"), ("kind", "VARCHAR(20) NOT NULL DEFAULT 'refresh'"), ("dataset_id", "VARCHAR(100) NULL"), ("import_mode", "VARCHAR(20) NULL"), ("is_simulated", "BOOLEAN NOT NULL DEFAULT 0")):
        if name not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
            try:
                with engine.begin() as connection:
                    connection.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {definition}"))
            except Exception:
                if name not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
                    raise
    if engine.dialect.name == 'mysql':
        column=next(c for c in inspect(engine).get_columns('jobs') if c['name']=='dataset_id')
        if (getattr(column['type'],'length',180) or 180)<180:
            with engine.begin() as connection:connection.execute(text('ALTER TABLE jobs MODIFY dataset_id VARCHAR(180) NULL'))
    from .data_activity import freeze_legacy_withdrawals
    with sessionmaker(bind=engine)() as session:freeze_legacy_withdrawals(session)
