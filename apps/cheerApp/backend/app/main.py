"""CheerApp backend — FastAPI service backed by Postgres (see app/db.py,
app/repository.py). Not wired into any other product's DI container on
purpose — see ../README.md.
"""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession

from app import repository as repo
from app.db import engine, get_session
from app.models import CheckinRequest, CheckinResponse, Event, Show, TimeResponse

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "show.schema.json"
_show_validator = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))

_ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets_store"
_ASSETS_DIR.mkdir(exist_ok=True)

_ASSET_CUE_TYPES = {"image", "video", "audio"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="CheerApp API", version="0.1.0", lifespan=lifespan)

# Wide open for now — the web client is served from a different origin
# (its own static server / future CDN) with no auth yet to scope this to.
# Tighten to specific origins once there's a real deployment target and/or
# auth lands (docs/ROADMAP.md Phase 1).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Dev-only static file host so Show.assets[].url points at something real
# for local testing (see ../README.md "Assets"). This is NOT the asset
# upload/CDN pipeline (docs/ROADMAP.md Phase 1 still open) — there's no
# upload endpoint, just a directory a producer drops files into by hand.
app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")


@app.get("/time", response_model=TimeResponse)
def get_time() -> TimeResponse:
    """t1/t2 for the client's SNTP-style offset calc (docs/SYNC_DESIGN.md §1).

    Deliberately the cheapest possible handler — any work done here adds
    directly to the asymmetry the offset math assumes is negligible.
    """
    t1 = time.time_ns() // 1_000_000
    t2 = time.time_ns() // 1_000_000
    return TimeResponse(t1=t1, t2=t2)


@app.post("/events", response_model=Event, status_code=201)
async def create_event(event: Event, session: AsyncSession = Depends(get_session)) -> Event:
    try:
        return await repo.put_event(session, event)
    except repo.EventAlreadyExists:
        raise HTTPException(status_code=409, detail=f"event {event.eventId!r} already exists")


@app.get("/events/{event_id}", response_model=Event)
async def get_event(event_id: str, session: AsyncSession = Depends(get_session)) -> Event:
    event = await repo.get_event(session, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    return event


@app.post("/events/{event_id}/shows", response_model=Show)
async def publish_show(event_id: str, show: Show, session: AsyncSession = Depends(get_session)) -> Show:
    if not await repo.get_event(session, event_id):
        raise HTTPException(status_code=404, detail="event not found")
    if show.eventId != event_id:
        raise HTTPException(status_code=400, detail="show.eventId does not match URL")

    errors = sorted(_show_validator.iter_errors(json.loads(show.model_dump_json())), key=str)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=[f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors],
        )

    # The JSON Schema can't express "assetId must exist in assets[]" as a
    # cross-array reference, so check it here. Catching a dangling
    # assetId at publish time — not live, as a missing render at showtime
    # — is the whole point of pre-fetching assets ahead of the show
    # (docs/ARCHITECTURE.md §5): a cue an AssetStore can't resolve is
    # exactly the live network dependency that's supposed to be
    # impossible by showtime.
    known_asset_ids = {a.assetId for a in show.assets}
    missing = sorted(
        {
            cue.params["assetId"]
            for cue in show.cues
            if cue.type in _ASSET_CUE_TYPES and cue.params.get("assetId") not in known_asset_ids
        }
    )
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"cue(s) reference assetId(s) not present in show.assets: {missing}",
        )

    return await repo.put_show(session, show)


@app.get("/events/{event_id}/show", response_model=Show)
async def get_show(event_id: str, session: AsyncSession = Depends(get_session)) -> Show:
    show = await repo.get_show(session, event_id)
    if not show:
        raise HTTPException(status_code=404, detail="no published show for this event")
    return show


@app.post("/events/{event_id}/checkin", response_model=CheckinResponse)
async def checkin(event_id: str, body: CheckinRequest, session: AsyncSession = Depends(get_session)) -> CheckinResponse:
    zone_id = await repo.resolve_qr_token(session, event_id, body.qrToken)
    if not zone_id:
        raise HTTPException(status_code=404, detail="unrecognized QR token for this event")
    return CheckinResponse(zoneId=zone_id)


# --- Live control channel -------------------------------------------------
# Convenience for operator overrides (go-live / delay / abort). Never the
# sync mechanism itself — see docs/ARCHITECTURE.md §4. Fan-out only, no
# per-connection state beyond membership in an event's room.

class _EventRoom:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.discard(ws)


_rooms: dict[str, _EventRoom] = {}


@app.websocket("/events/{event_id}/live")
async def live_control(websocket: WebSocket, event_id: str) -> None:
    await websocket.accept()
    room = _rooms.setdefault(event_id, _EventRoom())
    room.connections.add(websocket)
    try:
        while True:
            # Only an operator client is expected to send; fans just
            # listen. Any inbound message is broadcast verbatim to the
            # room (e.g. {"type": "abort", "cueId": "c2"}).
            message = await websocket.receive_json()
            await room.broadcast(message)
    except WebSocketDisconnect:
        room.connections.discard(websocket)
