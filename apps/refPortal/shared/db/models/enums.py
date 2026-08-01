from enum import Enum


class GameState(str, Enum):
    active = 'active'
    archived = 'archived'
    removed = 'removed'
    canceled = 'canceled'


class RefereeStatus(str, Enum):
    active = 'active'
    inactive = 'inactive'
    pilot = 'pilot'
    suspended = 'suspended'


class MessageDirection(str, Enum):
    inbound = 'in'
    outbound = 'out'


class TournamentType(str, Enum):
    league = 'league'
    cup = 'cup'
    practice = 'practice'


class TemplateStatus(str, Enum):
    created = 'created'
    sent = 'sent'
    failed = 'failed'
    completed = 'completed'


class NotificationTypeKey(str, Enum):
    """The fixed, code-driven notificationType values (as opposed to templateAction-derived ones,
    e.g. 'approvegame'/'gamereport', which are dynamic and can't be enumerated here) - see
    RefereeProcessService.getEffectiveNotificationSetting for the catalog/tenant/referee cascade
    most of these participate in."""
    gameFirstReminder = 'gameFirstReminder'
    refereeLastReminder = 'refereeLastReminder'
    gameLastReminder = 'gameLastReminder'
    gameLineupsAnnounced = 'gameLineupsAnnounced'
    refereeGameReport = 'refereeGameReport'
    refereeGameUpdate = 'refereeGameUpdate'
    refereeCommuteGameUpdate = 'refereeCommuteGameUpdate'
    chatGroupCreated = 'chatGroupCreated'
    transportationPoll = 'transportationPoll'
    addedItem = 'addedItem'
    removedItem = 'removedItem'
    archivedItem = 'archivedItem'
    updatedItem = 'updatedItem'
    assignmentsReplyReport = 'assignmentsReplyReport'
    joinChatGroup = 'joinChatGroup'
    openWindow = 'openWindow'
