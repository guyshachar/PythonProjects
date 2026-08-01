from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from shared.db.models.base import _Base
from shared.db.models.enums import GameState, TournamentType


class Tournament(_Base):
    tenant_id: int
    tournament_name: str
    tournament_type: TournamentType = TournamentType.league
    text: Optional[str] = None
    href: Optional[str] = None
    league_id: Optional[str] = None
    section_id: Optional[int] = None
    rule_id: Optional[int] = None
    properties: dict[str, Any] = {}


class TournamentGame(_Base):
    tournament_id: int
    game_pk: str
    game_id: Optional[str] = None
    game_title: Optional[str] = None
    home_team_id: int
    guest_team_id: int
    game_date: Optional[datetime] = None
    field_id: int
    fixture: Optional[str] = None
    round: Optional[str] = None
    url: Optional[str] = None
    group_name: Optional[str] = None
    group_mobile_numbers: Optional[str] = None
    state: GameState = GameState.active
    referees: list[dict[str, Any]] = []
    squads: Optional[dict[str, Any]] = None
    game_result: Optional[dict[str, Any]] = None
    carpool: Optional[dict[str, Any]] = None
    referee_ids: Optional[list[int]] = None
    main_referee_ids: Optional[list[int]] = None
    reviewer_id: Optional[int] = None   # FK → referees.id
    secretary_id: Optional[int] = None  # FK → referees.id
    properties: dict[str, Any] = {}


class TournamentGameHistory(_Base):
    tenant_id: int
    tournament_name: str
    game_pk: str
    history: dict[str, Any] = {}


class RefereeGame(_Base):
    referee_id: int
    tournament_game_id: int
    state: GameState = GameState.active
    role_id: Optional[int] = None
    status: Optional[str] = None
    internal_id: Optional[str] = None
    approved_date: Optional[datetime] = None
    declined_date: Optional[datetime] = None
    properties: dict[str, Any] = {}


class RefereeReview(_Base):
    referee_id: int
    tournament_game_id: int
    tenant_id: int
    state: GameState = GameState.active
    review_grade: Optional[str] = None
    reviewer: Optional[str] = None
    review_detail: Optional[dict[str, Any]] = None
    properties: dict[str, Any] = {}


class RefereeAvailability(_Base):
    referee_id: int
    availability_date: date
    availability_status: Optional[str] = None
    properties: dict[str, Any] = {}
