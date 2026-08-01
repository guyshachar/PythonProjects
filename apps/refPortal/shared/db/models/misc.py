from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from shared.db.models.base import _Base


class KeyVal(_Base):
    tenant_id: int
    key: str
    value: Optional[Any] = None


class ReferenceId(_Base):
    tenant_id: int
    target: str
    target_id: str
    value: Optional[Any] = None


class Invocation(_Base):
    tenant_id: int
    invocation_id: str
    details: dict[str, Any] = {}


class LeagueTable(_Base):
    tournament_id: int
    value: dict[str, Any] = {}


class Poll(_Base):
    tenant_id: int
    poll_name: str
    questions: list[Any] = []
    options: dict[str, Any] = {}
    properties: dict[str, Any] = {}


class PollVote(_Base):
    poll_id: int
    mobile_no: str
    question_id: str
    answer: Optional[str] = None
    properties: dict[str, Any] = {}


class CollectedItem(_Base):
    referee_id: int
    obj_type: str
    collection_data: dict[str, Any] = {}


class MediaFileMetadata(_Base):
    tenant_id: int
    file_id: str
    from_mobile: Optional[str] = None
    message_sid: Optional[str] = None
    properties: dict[str, Any] = {}


class RefereeLocation(_Base):
    referee_id: int
    recorded_at: datetime
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    properties: dict[str, Any] = {}


class PositionUpdate(_Base):
    referee_id: int
    recorded_at: datetime
    coordinates: dict[str, Any] = {}
    properties: dict[str, Any] = {}


class RateLimiter(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    time_window: str
    used: int = 0
    expire_at: datetime
