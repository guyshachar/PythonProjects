"""Async repository — Postgres-backed replacement for the old in-memory
store.py. One function per operation main.py needs; each takes the
request's AsyncSession (see app/db.py's get_session dependency) and
returns/accepts the Pydantic models from app/models.py, never the ORM
rows directly, so main.py stays storage-agnostic.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db_models import AssetORM, CueORM, EventORM, ShowORM, ZoneORM
from app.models import Asset, Cue, Event, Show, Zone


class EventAlreadyExists(Exception):
    pass


async def put_event(session: AsyncSession, event: Event) -> Event:
    orm = EventORM(
        event_id=event.eventId,
        name=event.name,
        venue=event.venue,
        start_time_utc=event.startTimeUtc,
        created_at=event.createdAt,
        zones=[ZoneORM(event_id=event.eventId, zone_id=z.zoneId, label=z.label, qr_token=z.qrToken) for z in event.zones],
    )
    session.add(orm)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EventAlreadyExists(event.eventId) from exc
    return event


async def get_event(session: AsyncSession, event_id: str) -> Event | None:
    orm = await session.get(EventORM, event_id, options=[selectinload(EventORM.zones)])
    if orm is None:
        return None
    return _event_from_orm(orm)


async def put_show(session: AsyncSession, show: Show) -> Show:
    """Appends a new show row — publishing never overwrites history, see
    app/db_models.py's ShowORM docstring. get_show() returns the latest.
    """
    orm = ShowORM(
        show_id=show.showId,
        event_id=show.eventId,
        schema_version=show.schemaVersion,
        start_at_utc=show.startAtUtc,
        created_at=show.createdAt,
        assets=[
            AssetORM(asset_id=a.assetId, type=a.type, url=a.url, sha256=a.sha256) for a in show.assets
        ],
        cues=[
            CueORM(
                cue_id=c.id,
                offset_ms=c.offsetMs,
                duration_ms=c.durationMs,
                type=c.type,
                params=c.params,
                zones=c.zones,
            )
            for c in show.cues
        ],
    )
    session.add(orm)
    await session.commit()
    return show


async def get_show(session: AsyncSession, event_id: str) -> Show | None:
    stmt = (
        select(ShowORM)
        .where(ShowORM.event_id == event_id)
        .order_by(ShowORM.id.desc())
        .limit(1)
        .options(selectinload(ShowORM.assets), selectinload(ShowORM.cues))
    )
    orm = (await session.execute(stmt)).scalar_one_or_none()
    if orm is None:
        return None
    return _show_from_orm(orm)


async def resolve_qr_token(session: AsyncSession, event_id: str, qr_token: str) -> str | None:
    stmt = select(ZoneORM.zone_id).where(ZoneORM.event_id == event_id, ZoneORM.qr_token == qr_token)
    return (await session.execute(stmt)).scalar_one_or_none()


def _event_from_orm(orm: EventORM) -> Event:
    return Event(
        eventId=orm.event_id,
        name=orm.name,
        venue=orm.venue,
        startTimeUtc=orm.start_time_utc,
        createdAt=orm.created_at,
        zones=[Zone(zoneId=z.zone_id, label=z.label, qrToken=z.qr_token) for z in orm.zones],
    )


def _show_from_orm(orm: ShowORM) -> Show:
    return Show(
        schemaVersion=orm.schema_version,
        showId=orm.show_id,
        eventId=orm.event_id,
        startAtUtc=orm.start_at_utc,
        createdAt=orm.created_at,
        assets=[Asset(assetId=a.asset_id, type=a.type, url=a.url, sha256=a.sha256) for a in orm.assets],
        cues=[
            Cue(id=c.cue_id, offsetMs=c.offset_ms, durationMs=c.duration_ms, type=c.type, params=c.params, zones=c.zones)
            for c in orm.cues
        ],
    )
