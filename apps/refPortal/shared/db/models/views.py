"""Read-optimised view models — flattened/combined shapes returned to the PWA.

These are *not* DB row models; they represent the denormalised objects that the
API assembles from multiple cache/DB sources before sending JSON to the client.
None of the existing code uses these yet.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from shared.db.models.enums import GameState


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------

class SyncMeta(BaseModel):
    """Metadata about the last automation run and last data update."""
    lastRun: Optional[datetime] = None
    lastUpdate: Optional[datetime] = None


class FieldDataView(BaseModel):
    """Venue details embedded inside game/review views."""
    model_config = ConfigDict(extra='allow')

    id: Optional[int] = None
    fieldName: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    wazeLink: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    level: Optional[str] = None


class TournamentDataView(BaseModel):
    """Tournament metadata embedded inside game/review views."""
    model_config = ConfigDict(extra='allow')

    id: Optional[int] = None
    tournamentName: Optional[str] = None
    tournament: Optional[str] = None       # type: 'league' | 'cup' | 'practice'
    section: Optional[str] = None
    rules: Optional[str] = None
    href: Optional[str] = None
    leagueId: Optional[str] = None


# ---------------------------------------------------------------------------
# Carpool
# ---------------------------------------------------------------------------

class CarpoolPassenger(BaseModel):
    mobileNo: str
    name: Optional[str] = None


class CarpoolRouteStop(BaseModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    durationMinutes: Optional[float] = None
    distanceKm: Optional[float] = None


class CarpoolRoute(BaseModel):
    totalDurationMinutes: Optional[float] = None
    totalDistanceKm: Optional[float] = None
    stops: list[CarpoolRouteStop] = []
    googleMapsUrl: Optional[str] = None
    computedAt: Optional[datetime] = None


class CarpoolCar(BaseModel):
    driverMobileNo: str
    driverName: Optional[str] = None
    passengers: list[CarpoolPassenger] = []
    route: Optional[CarpoolRoute] = None


class CarpoolView(BaseModel):
    cars: list[CarpoolCar] = []
    updatedAt: Optional[datetime] = None
    updatedBy: Optional[str] = None


# ---------------------------------------------------------------------------
# Game view  (pwaGetRefereeGames)
# ---------------------------------------------------------------------------

class GameRefereeAddress(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None


class GameRefereeView(BaseModel):
    """A referee as embedded inside a game card."""
    model_config = ConfigDict(extra='allow', populate_by_name=True)

    name: Optional[str] = None
    phone: Optional[str] = None     # field key is '* phone' in raw data
    role: Optional[str] = None
    address: Optional[GameRefereeAddress] = None


class GameView(BaseModel):
    """Full game card sent to the PWA for a logged-in referee."""
    model_config = ConfigDict(extra='allow')

    # Identity
    id: Optional[int] = None
    gamePk: Optional[str] = None
    gameId: Optional[str] = None
    gameTitle: Optional[str] = None

    # Schedule
    date: Optional[datetime] = None
    scheduledDate: Optional[datetime] = None
    fixture: Optional[str] = None
    round: Optional[str] = None

    # Teams
    homeTeamName: Optional[str] = None
    guestTeamName: Optional[str] = None

    # Venue
    field: Optional[str] = None
    fieldData: Optional[FieldDataView] = None

    # State & result
    state: Optional[GameState] = None
    gameResult: Optional[dict[str, Any]] = None

    # People
    referees: list[GameRefereeView] = []
    mainReferees: Optional[list[dict[str, Any]]] = None

    # Tournament context
    tournamentName: Optional[str] = None
    tournamentData: Optional[TournamentDataView] = None

    # Tenant context
    tenantKey: Optional[str] = None
    tenantName: Optional[str] = None
    tenantIcon: Optional[str] = None

    # Extras
    url: Optional[str] = None
    icalUrl: Optional[str] = None
    groupName: Optional[str] = None
    carpool: Optional[CarpoolView] = None


# ---------------------------------------------------------------------------
# Review view  (pwaGetRefereeReviews)
# ---------------------------------------------------------------------------

class ReviewView(BaseModel):
    """Game review card sent to the PWA."""
    model_config = ConfigDict(extra='allow')

    # Identity
    id: Optional[int] = None

    # Review fields
    reviewGrade: Optional[str] = None
    reviewer: Optional[str] = None
    reviewDetail: Optional[dict[str, Any]] = None
    state: Optional[GameState] = None

    # Embedded game context (merged at API layer)
    gamePk: Optional[str] = None
    tournamentName: Optional[str] = None
    tournamentData: Optional[TournamentDataView] = None
    date: Optional[datetime] = None
    field: Optional[str] = None
    fieldData: Optional[FieldDataView] = None
    fixture: Optional[str] = None
    role: Optional[str] = None

    # Tenant context
    tenantKey: Optional[str] = None


# ---------------------------------------------------------------------------
# Availability view  (pwaGetAvailability)
# ---------------------------------------------------------------------------

class AvailabilityDayView(BaseModel):
    id: Optional[int] = None
    mobileNo: str
    date: str                         # ISO date string 'YYYY-MM-DD'
    status: str = 'available'         # 'available' | 'unavailable' | 'partial'
    fromTime: Optional[str] = None
    toTime: Optional[str] = None
    isConsistent: Optional[Any] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Field search view  (pwaGetFields)
# ---------------------------------------------------------------------------

class FieldSearchView(BaseModel):
    """A venue item in the fields search/list response."""
    model_config = ConfigDict(extra='allow')

    id: Optional[int] = None
    fieldName: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    wazeLink: Optional[str] = None
    contact: Optional[str] = None
    phone: Optional[str] = None
    tenantKey: Optional[str] = None


# ---------------------------------------------------------------------------
# User settings view  (pwaGetUserDetails / pwaUpdateUserDetails)
# ---------------------------------------------------------------------------

class UserDetailsView(BaseModel):
    originAddress: str = ''
    telegramUsername: str = ''
    sendMessagesToTelegram: bool = False
    messageAcceptanceLimitation: bool = True
    availableFromHour: str = '7'
    availableToHour: str = '21'
    notificationSettings: list[dict] = []
    timeArrivalInAdvance: str = '45'
    calendarName: str = ''
    tenantRefIds: dict[str, Optional[str]] = {}


# ---------------------------------------------------------------------------
# Dashboard view  (pwaDashboardLoadData)
# ---------------------------------------------------------------------------

class DashboardView(BaseModel):
    gamesCount: int = 0
    activeRefereesCount: int = 0
    totalRefereesCount: int = 0
    todayGamesCount: int = 0
    refereeGamesCount: int = 0
    assignments24HrsCount: int = 0
    gameApprovals24HrsCount: int = 0
    gameResultUpdates24HrsCount: int = 0


# ---------------------------------------------------------------------------
# Referee list view  (pwaGetReferees — admin only)
# ---------------------------------------------------------------------------

class RefereeListView(BaseModel):
    id: Optional[int] = None
    mobileNo: str
    name: str = ''
    activeTenantKeys: list[str] = []
    passwordExists: bool = False


# ---------------------------------------------------------------------------
# Public game view  (getPublicGames)
# ---------------------------------------------------------------------------

class PublicGameView(BaseModel):
    """Game item returned by the public games endpoint (no auth required)."""
    model_config = ConfigDict(extra='allow')

    id: Optional[int] = None
    tournamentGameId: Optional[str] = None
    gameTitle: Optional[str] = None
    homeTeamName: Optional[str] = None
    guestTeamName: Optional[str] = None
    date: Optional[datetime] = None
    scheduledDate: Optional[datetime] = None
    field: Optional[str] = None
    fixture: Optional[str] = None
    round: Optional[str] = None
    state: Optional[GameState] = None
    referees: list[dict[str, Any]] = []
    gameResult: Optional[dict[str, Any]] = None
    tournamentName: Optional[str] = None
    sectionName: Optional[str] = None
    tenantKey: Optional[str] = None
    tenantName: Optional[str] = None
