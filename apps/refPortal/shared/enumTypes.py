from enum import Enum
from typing import Any

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
    DOCUMENTS = 'documents'
    TENANTS = 'tenants'
    REFEREEGAMES = 'refereeGames'
    REFEREEREVIEWS = 'refereeReviews'
    TOURNAMENTSGAMES = 'tournamentGames'
    TOURNAMENTSGAMESINDEX = 'tournamentGamesIndex'
    TOURNAMENTSGAMESINDEXBYFIELD = 'tournamentGamesIndexByField'
    TOURNAMENTSGAMESINDEXBYDATE = 'tournamentGamesIndexByDate'
    TOURNAMENTSGAMESINDEXQUERY = 'tournamentGamesIndexQuery'
    TOURNAMENTGAMESARCHIVED = 'tournamentGamesArchived'
    COLLECTEDITEMS = 'collectedItems'
    POSITIONUPDATES = 'positionUpdates'
    REFEREELOCATIONS = 'refereeLocations'
    POLLS = 'polls'
    POLLVOTES = 'pollVotes'
    
    def __str__(self) -> str:
        return str(self.value)

class ActionType(Enum):
    GET = 'get'
    SET = 'set'
    COUNT = 'count'

    def __str__(self) -> str:
        return str(self.value)