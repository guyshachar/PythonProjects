"""
Database setup — shared by the FastAPI app and the Celery worker.
"""

import os
from datetime import datetime
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from web.models import Base, JobRecord  # noqa: F401 (re-exported)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./scoutcut.db")  # Docker default: sqlite:////app/data/scoutcut.db

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite only
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: str | None = None,
    output_links: list | None = None,
    error: str | None = None,
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
        job.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
