"""SQLAlchemy ORM models — the Postgres-facing shape.

Mirrors app/models.py (the Pydantic/API-facing shape); app/repository.py
converts between the two. Kept as a separate layer rather than making the
Pydantic models double as ORM models so the wire contract
(app/models.py, mirroring shared/show.schema.json) can evolve
independently of storage details.

A published Show is never overwritten — publishing appends a new row and
`get_show(event_id)` returns the most recently published one (ordered by
the surrogate `id`, not by client-supplied timestamps). This gives show
publish history for free; nothing here surfaces that history via the API
yet, but it's sitting in the table if a future "show revisions" endpoint
wants it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# All datetimes here are UTC and timezone-aware on the Pydantic side
# (app/models.py) — map them to `timestamptz`, not Postgres's default
# naive `timestamp`, or asyncpg rejects offset-aware values on insert.
_UtcDateTime = DateTime(timezone=True)


class EventORM(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    venue: Mapped[str]
    start_time_utc: Mapped[datetime] = mapped_column(_UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(_UtcDateTime)

    zones: Mapped[list["ZoneORM"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="ZoneORM.zone_id"
    )


class ZoneORM(Base):
    __tablename__ = "zones"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"), primary_key=True)
    zone_id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str]
    qr_token: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    event: Mapped[EventORM] = relationship(back_populates="zones")


class ShowORM(Base):
    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)  # publish order, internal only
    show_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"), index=True)
    schema_version: Mapped[str]
    start_at_utc: Mapped[datetime] = mapped_column(_UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(_UtcDateTime)

    assets: Mapped[list["AssetORM"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    cues: Mapped[list["CueORM"]] = relationship(
        back_populates="show", cascade="all, delete-orphan", order_by="CueORM.offset_ms"
    )


class AssetORM(Base):
    __tablename__ = "assets"

    show_pk: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str]
    url: Mapped[str]
    sha256: Mapped[str | None] = mapped_column(String, nullable=True)

    show: Mapped[ShowORM] = relationship(back_populates="assets")


class CueORM(Base):
    __tablename__ = "cues"

    show_pk: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), primary_key=True)
    cue_id: Mapped[str] = mapped_column(String, primary_key=True)
    offset_ms: Mapped[int]
    duration_ms: Mapped[int]
    type: Mapped[str]
    params: Mapped[dict] = mapped_column(JSONB)
    zones: Mapped[list[str]] = mapped_column(JSONB)

    show: Mapped[ShowORM] = relationship(back_populates="cues")
