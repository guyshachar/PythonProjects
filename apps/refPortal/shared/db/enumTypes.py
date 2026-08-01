from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional, Type

if TYPE_CHECKING:
    from pydantic import BaseModel


class EntityType(Enum):
    INVOCATIONS = 'invocations'
    NOTIFICATIONS = 'notifications'
    REFERENCEIDS = 'referenceIds'
    KEYVAL = 'keyVal'
    MESSAGES = 'messages'
    REFEREEMESSAGES = 'refereeMessages'
    REFEREETEMPLATES = 'refereeTemplates'
    REFEREEAVAILABILITY = 'refereeAvailability'
    CLIENTIDENTIFIERS = 'clientIdentifiers'
    MEDIAFILEMETADATA = 'mediaFileMetadata'
    LEAGUETABLES = 'leagueTables'
    FIELDS = 'fields'
    TOURNAMENTS = 'tournaments'
    SEASONS = 'seasons'
    RULES = 'rules'
    SECTIONS = 'sections'
    ROLES = 'roles'
    REFEREES = 'referees'
    AREAS = 'areas'
    NOTIFICATIONTYPES = 'notificationTypes'
    DOCUMENTS = 'documents'
    TENANTS = 'tenants'
    REFEREEGAMES = 'refereeGames'
    REFEREEREVIEWS = 'refereeReviews'
    TOURNAMENTSGAMES = 'tournamentGames'
    TOURNAMENTGAMESARCHIVED = 'tournamentGamesArchived'
    COLLECTEDITEMS = 'collectedItems'
    POSITIONUPDATES = 'positionUpdates'
    REFEREELOCATIONS = 'refereeLocations'
    POLLS = 'polls'
    POLLVOTES = 'pollVotes'

    def __str__(self) -> str:
        return str(self.value)

    @property
    def model(self) -> Optional[Type[BaseModel]]:
        """Return the Pydantic model class that represents this entity type, or None."""
        from shared.db.models import (
            Area, ClientIdentifier, CollectedItem, Document, Field,
            Invocation, KeyVal, LeagueTable, MediaFileMetadata,
            Message, Notification, NotificationType, Poll, PollVote, PositionUpdate,
            Referee, RefereeAvailability, RefereeGame, RefereeLocation,
            RefereeMessage, RefereeReview, RefereeTemplate, ReferenceId,
            Role, Rule, Season, Section, Tenant,
            Tournament, TournamentGame,
        )
        _map: dict[EntityType, Type[BaseModel]] = {
            EntityType.TENANTS:                 Tenant,
            EntityType.SEASONS:                 Season,
            EntityType.SECTIONS:                Section,
            EntityType.ROLES:                   Role,
            EntityType.RULES:                   Rule,
            EntityType.FIELDS:                  Field,
            EntityType.DOCUMENTS:               Document,
            EntityType.AREAS:                   Area,
            EntityType.NOTIFICATIONTYPES:       NotificationType,
            EntityType.REFEREES:                Referee,
            EntityType.REFEREEGAMES:            RefereeGame,
            EntityType.REFEREEREVIEWS:          RefereeReview,
            EntityType.REFEREEAVAILABILITY:     RefereeAvailability,
            EntityType.TOURNAMENTS:             Tournament,
            EntityType.TOURNAMENTSGAMES:        TournamentGame,
            EntityType.TOURNAMENTGAMESARCHIVED: TournamentGame,
            EntityType.INVOCATIONS:             Invocation,
            EntityType.NOTIFICATIONS:           Notification,
            EntityType.REFERENCEIDS:            ReferenceId,
            EntityType.KEYVAL:                  KeyVal,
            EntityType.MESSAGES:                Message,
            EntityType.REFEREEMESSAGES:         RefereeMessage,
            EntityType.REFEREETEMPLATES:        RefereeTemplate,
            EntityType.CLIENTIDENTIFIERS:       ClientIdentifier,
            EntityType.MEDIAFILEMETADATA:       MediaFileMetadata,
            EntityType.LEAGUETABLES:            LeagueTable,
            EntityType.COLLECTEDITEMS:          CollectedItem,
            EntityType.POSITIONUPDATES:         PositionUpdate,
            EntityType.REFEREELOCATIONS:        RefereeLocation,
            EntityType.POLLS:                   Poll,
            EntityType.POLLVOTES:               PollVote,
        }
        return _map.get(self)

class ActionType(Enum):
    GET = 'get'
    SET = 'set'
    COUNT = 'count'

    def __str__(self) -> str:
        return str(self.value)