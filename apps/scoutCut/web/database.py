"""
Database setup — shared by the FastAPI app and the Celery worker.
"""

import os
from datetime import datetime, timedelta
from typing import Generator, List, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from web.models import Base, CachedResult, JobRecord  # noqa: F401 (re-exported)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./scoutcut.db")  # Docker default: sqlite:////app/data/scoutcut.db

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite only
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)   # creates link_cache automatically on new DBs
    # Migrations for existing DBs
    from sqlalchemy import text
    with engine.connect() as conn:
        for ddl in [
            "ALTER TABLE jobs ADD COLUMN report TEXT",
            "ALTER TABLE jobs ADD COLUMN from_cache TEXT",
            "ALTER TABLE jobs ADD COLUMN worker TEXT",
        ]:
            try:
                conn.execute(text(ddl))
                conn.commit()
            except Exception:
                pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


CACHE_TTL_DAYS = 7


def get_cached_result(cache_key: str) -> Optional[List[str]]:
    """Return cached output_links if unexpired, else None."""
    db = SessionLocal()
    try:
        row: CachedResult | None = db.get(CachedResult, cache_key)
        if row is None:
            return None
        if row.expires_at < datetime.utcnow():
            db.delete(row)
            db.commit()
            return None
        return row.output_links
    finally:
        db.close()


def store_cached_result(cache_key: str, output_links: List[str]) -> None:
    """Upsert a cache entry with a 7-day TTL."""
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        row: CachedResult | None = db.get(CachedResult, cache_key)
        if row is None:
            row = CachedResult(cache_key=cache_key)
            db.add(row)
        row.output_links = output_links
        row.created_at   = now
        row.expires_at   = now + timedelta(days=CACHE_TTL_DAYS)
        db.commit()
    finally:
        db.close()


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: str | None = None,
    output_links: list | None = None,
    error: str | None = None,
    report: str | None = None,
    worker: str | None = None,
) -> None:
    """Thread/process-safe helper used from the Celery worker."""
    db = SessionLocal()
    try:
        job: JobRecord | None = db.get(JobRecord, job_id)
        if job is None:
            return
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = progress
        if output_links is not None:
            job.output_links = output_links
        if error is not None:
            job.error = error
        if report is not None:
            job.report = report
        if worker is not None:
            job.worker = worker
        job.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
