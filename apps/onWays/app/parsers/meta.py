"""
MetaCloudWebhookParser – concrete Strategy for Meta Cloud API payloads.

Meta delivers a deeply-nested Graph API envelope.  Messages are under
entry[0].changes[0].value.messages; statuses under .statuses.

Supported message types (Phase 4):
  text     – body in msg["text"]["body"]
  image    – meta in msg["image"] {id, mime_type, caption}
  audio    – meta in msg["audio"] {id, mime_type}
  video    – meta in msg["video"] {id, mime_type, caption}
  document – meta in msg["document"] {id, mime_type, filename, caption}
  sticker  – meta in msg["sticker"] {id, mime_type}

For media types, Meta does NOT provide a download URL in the webhook.
The CRM must call GET /v19.0/{media-id} with an access token to retrieve it.
We surface `media_id` so the CRM can do this lookup.

References:
  https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
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

# Meta message type → our MediaType (text has no MediaType).
_META_MEDIA_TYPE_MAP: dict[str, MediaType] = {
    "image":    MediaType.IMAGE,
    "audio":    MediaType.AUDIO,
    "video":    MediaType.VIDEO,
    "document": MediaType.DOCUMENT,
    "sticker":  MediaType.STICKER,
}


def _epoch_to_utc(ts: str | int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


class MetaCloudWebhookParser(IWebhookParser):
    """Parses Meta Cloud API webhook payloads into the OnWays unified schema."""

    def can_parse(self, payload: dict) -> bool:
        return payload.get("object") == "whatsapp_business_account"

    def parse(self, payload: dict) -> ParsedEvent:
        try:
            value: dict = payload["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Meta payload has unexpected structure: {exc}") from exc

        to_number: str = value.get("metadata", {}).get("display_phone_number", "unknown")

        if "messages" in value:
            return self._parse_message(value, to_number)
        if "statuses" in value:
            return self._parse_status(value, to_number)

        raise NotImplementedError(
            "MetaCloudWebhookParser: payload contains neither 'messages' nor 'statuses'."
        )

    # -----------------------------------------------------------------------

    def _parse_message(self, value: dict, to_number: str) -> UnifiedMessage:
        try:
            msg: dict = value["messages"][0]
            msg_id: str = msg["id"]
            from_number: str = msg["from"]
            timestamp = _epoch_to_utc(msg["timestamp"])
            msg_type: str = msg.get("type", "text")
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Meta message payload missing required field: {exc}") from exc

        # Contact name
        contact_name: Optional[str] = None
        contacts = value.get("contacts", [])
        if contacts:
            contact_name = contacts[0].get("profile", {}).get("name")

        # ── Text ─────────────────────────────────────────────────────────────
        if msg_type == "text":
            body = msg.get("text", {}).get("body", "")
            return UnifiedMessage(
                message_id=msg_id,
                from_number=from_number,
                to_number=to_number,
                body=body,
                timestamp=timestamp,
                provider=ChannelProvider.META_CLOUD,
                direction=MessageDirection.INBOUND,
                contact_name=contact_name,
            )

        # ── Media ─────────────────────────────────────────────────────────────
        media_type = _META_MEDIA_TYPE_MAP.get(msg_type)
        if media_type is None:
            raise NotImplementedError(
                f"MetaCloudWebhookParser: message type '{msg_type}' is not yet supported."
            )

        media_obj: dict = msg.get(msg_type, {})
        media_id: Optional[str] = media_obj.get("id")
        media_mime_type: Optional[str] = media_obj.get("mime_type")
        media_filename: Optional[str] = media_obj.get("filename")       # documents only
        body = media_obj.get("caption", "")                              # optional caption

        return UnifiedMessage(
            message_id=msg_id,
            from_number=from_number,
            to_number=to_number,
            body=body,
            timestamp=timestamp,
            provider=ChannelProvider.META_CLOUD,
            direction=MessageDirection.INBOUND,
            contact_name=contact_name,
            media_type=media_type,
            media_id=media_id,
            media_mime_type=media_mime_type,
            media_filename=media_filename,
        )

    def _parse_status(self, value: dict, to_number: str) -> UnifiedReadReceipt:
        try:
            status_obj: dict = value["statuses"][0]
            msg_id: str = status_obj["id"]
            from_number: str = status_obj["recipient_id"]
            raw_status: str = status_obj["status"]
            timestamp = _epoch_to_utc(status_obj["timestamp"])
        except (KeyError, IndexError) as exc:
            raise ValueError(f"Meta status payload missing required field: {exc}") from exc

        try:
            status = DeliveryStatus(raw_status)
        except ValueError:
            status = DeliveryStatus.SENT

        return UnifiedReadReceipt(
            message_id=msg_id,
            from_number=from_number,
            to_number=to_number,
            status=status,
            timestamp=timestamp,
            provider=ChannelProvider.META_CLOUD,
        )
