"""In-memory store — prototype only.

Swap this for a real datastore (this monorepo already has Redis/DynamoDB
plumbing in shared/ if CheerApp ends up wanting to reuse it) before
anything here handles a real event. Kept deliberately dumb so the API
contract in main.py can be exercised and tested without infra.
"""
from __future__ import annotations

from app.models import Event, Show


class Store:
    def __init__(self) -> None:
        self.events: dict[str, Event] = {}
        self.shows: dict[str, Show] = {}  # keyed by eventId -> current published show

    def put_event(self, event: Event) -> Event:
        self.events[event.eventId] = event
        return event

    def get_event(self, event_id: str) -> Event | None:
        return self.events.get(event_id)

    def put_show(self, show: Show) -> Show:
        self.shows[show.eventId] = show
        return show

    def get_show(self, event_id: str) -> Show | None:
        return self.shows.get(event_id)

    def resolve_qr_token(self, event_id: str, qr_token: str) -> str | None:
        event = self.get_event(event_id)
        if not event:
            return None
        for zone in event.zones:
            if zone.qrToken == qr_token:
                return zone.zoneId
        return None


store = Store()
