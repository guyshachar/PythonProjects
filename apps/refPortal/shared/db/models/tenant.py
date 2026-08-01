from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from shared.db.models.base import _Base


class Tenant(_Base):
    tenant_key: str
    country_code: Optional[str] = None
    event_type: Optional[str] = None
    season: Optional[str] = None
    name: Optional[str] = None
    active: bool = False
    active_status: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    game_duration_in_mins: int = 120
    assigner_collection: bool = False
    # Per-tenant opt-in for the manual-game-assignment feature (see apply_manual_games.py) -
    # referees can only self-report a game for a tenant with this enabled.
    allow_manual_games: bool = False
    # Maps tournament_type enum values (see postgres_ddl.sql's `tournament_type` enum:
    # league/cup/practice) to their Hebrew display label for this tenant's manual-game form -
    # e.g. {"league": "ליגה", "cup": "גביע"}. Lets a tenant that only ever runs league play skip
    # showing cup/practice as options. See apply_tournament_types.py / apply_tournament_types_as_object.py.
    tournament_types: dict[str, str] = {'league': 'ליגה'}
    # WhatsApp / notifications
    whats_app_group_link: Optional[str] = None
    main_assigner: Optional[str] = None
    game_update_tags: dict[str, Any] = {}
    notifications: dict[str, Any] = {}
    # Tenant-level relevance/overrides of notification_types, keyed by type_key - distinct from
    # `notifications` above (an older, unrelated hour-settings dict). See
    # getEffectiveNotificationSetting in shared/refereeProcessService.py.
    notification_settings: dict[str, Any] = {}
    skip_availability_notifications: list[Any] = []
    default_available_from_hour: int = 8
    default_available_to_hour: int = 21
    # Scraping / data pipeline
    obj_types: list[str] = []
    games_reports_obj_type: Optional[str] = None
    status_after_failed_login: Optional[str] = None
    minimum_removals_to_ignore: int = 1
    # Media / display
    icon: Optional[str] = None
    media_file_types: dict[str, Any] = {}
    # PWA feature-visibility flags (approveGame/liveGame/gameReport/updateReport/openReport/gameDetails)
    buttons: dict[str, Any] = {}
    # Org-specific config (IHA: login/logout URLs; IFA: unused)
    urls: dict[str, Any] = {}
    collect_type: str = 'byAssigner'
    temporary_password: Optional[str] = None
    assignments_reply_report_to: Optional[str] = None
    properties: dict[str, Any] = {}


class Season(_Base):
    season_name: str
    properties: dict[str, Any] = {}


class Section(_Base):
    tenant_id: Optional[int] = None
    section_name: str
    display_order: Optional[int] = None
    table_result: Optional[Any] = None
    skip_referee_game_update_reminder: bool = False
    properties: dict[str, Any] = {}


class Role(_Base):
    tenant_id: Optional[int] = None
    role_name: str
    order: Optional[str] = None
    display_order: Optional[int] = None
    role_type: Optional[str] = None
    main_referee: bool = False
    secretary_referee: bool = False
    reviewer: bool = False
    properties: dict[str, Any] = {}


class Rule(_Base):
    tenant_id: Optional[int] = None
    rule_name: str
    game_gross_time: Optional[int] = None
    cup_gross_time: Optional[int] = None
    include_reviewer: bool = False
    # Hebrew schedule breakdowns stored at top level in DynamoDB
    game: Optional[dict[str, Any]] = None
    cup: Optional[dict[str, Any]] = None
    match_setup: dict[str, Any] = {}
    properties: dict[str, Any] = {}


class AddressDetails(_Base):
    """Nested address structure used by DynamoDB-stored fields."""
    address: Optional[str] = None
    coordinates: Optional[dict[str, float]] = None
    waze_link: Optional[str] = None


class Field(_Base):
    # Postgres FK (absent in DynamoDB field dicts)
    tenant_id: Optional[int] = None
    field_name: str
    # DynamoDB display name (may differ from field_name)
    title: Optional[str] = None
    # Flat address columns (Postgres schema)
    address: Optional[str] = None
    formatted_address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    waze_link: Optional[str] = None
    # Contact info
    contact: Optional[str] = None
    phone: Optional[str] = None
    level: Optional[str] = None
    # Optional tenant scope stored inline in DynamoDB
    tenant_key: Optional[str] = None
    properties: dict[str, Any] = {}


class Document(_Base):
    tenant_id: Optional[int] = None
    document_name: str
    doc_file: Optional[str] = None
    properties: dict[str, Any] = {}
