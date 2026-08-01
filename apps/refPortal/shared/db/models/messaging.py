from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from shared.db.models.base import _Base
from shared.db.models.enums import MessageDirection, TemplateStatus


class RefereeMessage(_Base):
    referee_id: int
    direction: MessageDirection
    msg_sid: str
    content: Optional[str] = None
    sent_at: Optional[datetime] = None
    properties: dict[str, Any] = {}


class RefereeTemplate(_Base):
    referee_id: int
    action: str
    msg_sid: str
    status: TemplateStatus = TemplateStatus.created
    tournament_game_id: Optional[int] = None
    template_content: dict[str, Any] = {}
    properties: dict[str, Any] = {}


class ClientIdentifier(_Base):
    referee_id: int
    client_identifier: str
    session_identifier: Optional[str] = None
    push_subscription: Optional[dict[str, Any]] = None
    user_agent: Optional[str] = None
    platform: Optional[str] = None
    whatsapp_uuid: Optional[str] = None
    properties: dict[str, Any] = {}


class Notification(_Base):
    to_referee_id: Optional[int] = None
    target: str
    target_id: str
    notification_type: str
    event_timestamp: int
    status: Optional[str] = None
    properties: dict[str, Any] = {}


class Message(_Base):
    tenant_id: int
    msg_sid: str
    content: dict[str, Any] = {}
    properties: dict[str, Any] = {}
