"""Pydantic models for the CheerApp v1 contract.

Mirrors ../../shared/show.schema.json — that JSON Schema is the source of
truth for the wire format (validated explicitly in main.py on publish);
these models are the FastAPI-facing view of the same shape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

CueType = Literal["flash", "color", "image", "video", "audio"]
AssetType = Literal["image", "video", "audio"]


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Zone(BaseModel):
    zoneId: str
    label: str
    qrToken: str | None = None  # signed token printed on that zone's QR code


class Event(BaseModel):
    eventId: str = Field(default_factory=lambda: _new_id("event"))
    name: str
    venue: str
    startTimeUtc: datetime
    zones: list[Zone] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Asset(BaseModel):
    assetId: str
    type: AssetType
    url: str
    sha256: str | None = None


class Cue(BaseModel):
    id: str
    offsetMs: int = Field(ge=0)
    durationMs: int = Field(ge=0)
    type: CueType
    params: dict
    zones: list[str] = Field(min_length=1)  # zone ids, or ["ALL"]


class Show(BaseModel):
    schemaVersion: Literal["v1"] = "v1"
    showId: str = Field(default_factory=lambda: _new_id("show"))
    eventId: str
    startAtUtc: datetime
    assets: list[Asset] = Field(default_factory=list)
    cues: list[Cue] = Field(default_factory=list)


class CheckinRequest(BaseModel):
    qrToken: str


class CheckinResponse(BaseModel):
    zoneId: str


class TimeResponse(BaseModel):
    """t1/t2 for the client's SNTP-style calc — see docs/SYNC_DESIGN.md §1.

    t1: server-clock timestamp when the request was received.
    t2: server-clock timestamp when the response was written (kept
    distinct from t1 in case request handling has non-trivial cost).
    Both are epoch milliseconds, UTC.
    """
    t1: int
    t2: int
