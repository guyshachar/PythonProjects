"""Async SQLAlchemy engine/session plumbing.

Schema is managed by Alembic (../alembic/) — see ../README.md "Database"
section for the migration workflow. Nothing here calls
`Base.metadata.create_all`; a fresh dev DB is expected to run
`alembic upgrade head` once before the app starts.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import database_url


class Base(DeclarativeBase):
    pass


engine = create_async_engine(database_url(), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — one session per request, committed on success."""
    async with SessionLocal() as session:
        yield session
