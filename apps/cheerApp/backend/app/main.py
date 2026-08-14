"""CheerApp backend — prototype FastAPI service.

See ../README.md for the endpoint contract and cheerApp/docs/ for design.
Not wired into RefPortal's shared/ DI container on purpose — see README.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from jsonschema import Draft202012Validator

from app.models import CheckinRequest, CheckinResponse, Event, Show, TimeResponse
from app.store import store

app = FastAPI(title="CheerApp API", version="0.1.0")

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "show.schema.json"
_show_validator = Draft202012Validator(json.loads(_SCHEMA_PATH.read_text()))


@app.get("/time", response_model=TimeResponse)
def get_time() -> TimeResponse:
    """t1/t2 for the client's SNTP-style offset calc (docs/SYNC_DESIGN.md §1).

    Deliberately the cheapest possible handler — any work done here adds
    directly to the asymmetry the offset math assumes is negligible.
    """
    t1 = time.time_ns() // 1_000_000
    t2 = time.time_ns() // 1_000_000
    return TimeResponse(t1=t1, t2=t2)


@app.post("/events", response_model=Event)
def create_event(event: Event) -> Event:
    return store.put_event(event)


@app.get("/events/{event_id}", response_model=Event)
def get_event(event_id: str) -> Event:
    event = store.get_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    return event


@app.post("/events/{event_id}/shows", response_model=Show)
def publish_show(event_id: str, show: Show) -> Show:
    if not store.get_event(event_id):
        raise HTTPException(status_code=404, detail="event not found")
    if show.eventId != event_id:
        raise HTTPException(status_code=400, detail="show.eventId does not match URL")

    errors = sorted(_show_validator.iter_errors(json.loads(show.model_dump_json())), key=str)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=[f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors],
        )
    return store.put_show(show)


@app.get("/events/{event_id}/show", response_model=Show)
def get_show(event_id: str) -> Show:
    show = store.get_show(event_id)
    if not show:
        raise HTTPException(status_code=404, detail="no published show for this event")
    return show


@app.post("/events/{event_id}/checkin", response_model=CheckinResponse)
def checkin(event_id: str, body: CheckinRequest) -> CheckinResponse:
    zone_id = store.resolve_qr_token(event_id, body.qrToken)
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
