from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from shared.db.models.base import _Base
from shared.db.models.enums import RefereeStatus


class Referee(_Base):
    mobile_no: str
    name: Optional[str] = None
    gender: Optional[str] = None
    role: Optional[str] = None
    guid: Optional[UUID] = None
    color: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    origin_address: Optional[str] = None
    origin_location: Optional[dict[str, Any]] = None
    calendar_name: Optional[str] = None
    telegram_id: Optional[str] = None
    telegram_username: Optional[str] = None
    time_arrival_in_advance: Optional[int] = None
    avoid_night_messages: bool = False
    id_number: Optional[str] = None
    email: Optional[str] = None
    area_id: Optional[int] = None
    grade: Optional[str] = None
    occupation: Optional[str] = None
    send_messages_to_telegram: bool = False
    blocked_from_meta_templates: bool = False
    always_create_chat_group: bool = False
    ignore_group4singles: bool = False
    create_groups: bool = False
    window_is_open: bool = False
    force_use_green_api: bool = False
    available_from_hour: int = 7
    available_to_hour: int = 21
    active_tenant_keys: list[str] = []
    tenant_keys: list[str] = []
    properties: dict[str, Any] = {}


class TenantReferee(_Base):
    referee_id: int
    tenant_id: int
    ref_id: Optional[str] = None
    status: RefereeStatus = RefereeStatus.inactive
    role: Optional[str] = None
    portal_allow: bool = False
    internal_referee_id: Optional[int] = None
    properties: dict[str, Any] = {}


class Club(_Base):
    club_name: str
    tenant_id: int
    properties: dict[str, Any] = {}


class Team(_Base):
    tournament_id: int
    team_name: str
    club_id: Optional[int] = None
    properties: dict[str, Any] = {}


class Area(_Base):
    """Global (not tenant-scoped, like Referee itself): a named region, optionally assigned
    a referee (with the 'assigner' role) who handles that region's assigner-bot messages.
    referees.area_id points here."""
    area_name: str
    assigner_referee_id: Optional[int] = None
    properties: dict[str, Any] = {}


class NotificationType(_Base):
    """Global (not tenant-scoped) catalog entry describing one kind of notification: when it's
    due relative to context_time, and which channels it can go out on. tenants.notification_settings
    and referees.notification_overrides (both JSONB, keyed by type_key) layer on top of this as
    tenant- and referee-level overrides - see getEffectiveNotificationSetting in
    refereeProcessService.py for the resolution cascade."""
    type_key: str
    context_time: str  # 'created' | 'gameStart' | 'gameEnd'
    offset_minutes: int = 0  # +/- minutes relative to context_time
    channels: list[str] = []  # e.g. ["push", "meta", "greenApi", "telegram"]
    enabled: bool = True  # global kill switch - false overrides any tenant/referee opt-in
    seq: int = 0  # display order in a dynamically-rendered settings view
    properties: dict[str, Any] = {}
