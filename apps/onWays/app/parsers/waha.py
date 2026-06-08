"""
WahaWebhookParser – concrete Strategy for WAHA (WhatsApp HTTP API) payloads.

WAHA delivers a flat envelope:

    {
      "event": "message" | "message.ack",
      "session": "default",
      "payload": {
        "id":        "false_15551234567@c.us_AAA111",
        "from":      "15551234567@c.us",
        "to":        "15559876543@c.us",
        "body":      "Hello!",          # text body or media caption
        "timestamp": 1700000000,
        "fromMe":    false,
        "hasMedia":  false,             # true for image/audio/video/document
        "type":      "chat",            # "chat"=text, "image", "audio", "ptt", "video", "document", "sticker"
        "mediaUrl":  "http://...",      # present when hasMedia=true
        "_data": {
          "notifyName": "Alice",
          "mimetype": "image/jpeg"      # present when hasMedia=true
        }
      }
    }

For ACK events, payload.ack:  1=sent  2=delivered  3=read

References:
  https://waha.devlike.pro/docs/how-to/webhooks/
"""

from datetime import datetime, timezone
from typing import Optional

from app.models.unified import (
    ChannelProvider,
    DeliveryStatus,
    MediaType,
    MessageDirection,
    UnifiedMessage,
    UnifiedReadReceipt,
)
from app.parsers.base import IWebhookParser, ParsedEvent

_WAHA_ACK_MAP: dict[int, DeliveryStatus] = {
    1: DeliveryStatus.SENT,
    2: DeliveryStatus.DELIVERED,
    3: DeliveryStatus.READ,
}

# WAHA type → our MediaType.  "chat" is plain text (no MediaType).
_WAHA_MEDIA_TYPE_MAP: dict[str, MediaType] = {
    "image":    MediaType.IMAGE,
    "audio":    MediaType.AUDIO,
    "ptt":      MediaType.AUDIO,   # push-to-talk / voice note
    "video":    MediaType.VIDEO,
    "document": MediaType.DOCUMENT,
    "sticker":  MediaType.STICKER,
}


def _strip_suffix(number: str) -> str:
    """Remove '@c.us' / '@g.us' suffix that WAHA appends."""
    return number.split("@")[0]


def _epoch_to_utc(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


class WahaWebhookParser(IWebhookParser):
    """Parses WAHA webhook payloads into the OnWays unified schema."""

    def can_parse(self, payload: dict) -> bool:
        return (
            "event" in payload
            and "session" in payload
            and payload.get("event") in ("message", "message.ack")
        )

    def parse(self, payload: dict) -> ParsedEvent:
        event_type: str = payload["event"]
        inner: dict = payload.get("payload", {})

        if not inner:
            raise ValueError("WAHA payload missing 'payload' field.")

        if event_type == "message":
            return self._parse_message(inner)
        if event_type == "message.ack":
            return self._parse_ack(inner)

        raise NotImplementedError(f"WahaWebhookParser: unhandled event type '{event_type}'.")

    # -----------------------------------------------------------------------

    def _parse_message(self, inner: dict) -> UnifiedMessage:
        try:
            msg_id: str = inner["id"]
            from_raw: str = inner["from"]
            to_raw: str = inner["to"]
            body: str = inner.get("body", "")
            timestamp: datetime = _epoch_to_utc(int(inner["timestamp"]))
        except KeyError as exc:
            raise ValueError(f"WAHA message payload missing required field: {exc}") from exc

        contact_name: Optional[str] = inner.get("_data", {}).get("notifyName")
        direction = (
            MessageDirection.OUTBOUND if inner.get("fromMe") else MessageDirection.INBOUND
        )

        # ── Media fields ─────────────────────────────────────────────────────
        waha_type: str = inner.get("type", "chat")
        media_type: Optional[MediaType] = _WAHA_MEDIA_TYPE_MAP.get(waha_type)
        media_url: Optional[str] = inner.get("mediaUrl") if media_type else None
        media_mime_type: Optional[str] = (
            inner.get("_data", {}).get("mimetype") if media_type else None
        )
        # WAHA does not expose a separate media_id or filename in the webhook;
        # the mediaUrl can be used directly for download.
        media_filename: Optional[str] = inner.get("_data", {}).get("filename")

        return UnifiedMessage(
            message_id=msg_id,
            from_number=_strip_suffix(from_raw),
            to_number=_strip_suffix(to_raw),
            body=body,
            timestamp=timestamp,
            provider=ChannelProvider.WAHA,
            direction=direction,
            contact_name=contact_name,
            media_type=media_type,
            media_url=media_url,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
        )

    def _parse_ack(self, inner: dict) -> UnifiedReadReceipt:
        try:
            msg_id: str = inner["id"]
            from_raw: str = inner["from"]
            to_raw: str = inner["to"]
            timestamp: datetime = _epoch_to_utc(int(inner["timestamp"]))
            ack_code: int = int(inner["ack"])
        except KeyError as exc:
            raise ValueError(f"WAHA ack payload missing required field: {exc}") from exc

        status = _WAHA_ACK_MAP.get(ack_code, DeliveryStatus.SENT)

        return UnifiedReadReceipt(
            message_id=msg_id,
            from_number=_strip_suffix(from_raw),
            to_number=_strip_suffix(to_raw),
            status=status,
            timestamp=timestamp,
            provider=ChannelProvider.WAHA,
        )
