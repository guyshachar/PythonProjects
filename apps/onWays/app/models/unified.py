"""
Unified JSON schema for all messages emitted by the OnWays gateway to the CRM.

Every provider (WAHA, Meta Cloud API) produces different webhook shapes.
After normalization, every downstream event is one of these two models:
  - UnifiedMessage     – a text or media message received from a customer
  - UnifiedReadReceipt – a read/delivered status update for a sent message
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class ChannelProvider(str, Enum):
    WAHA = "waha"
    META_CLOUD = "meta_cloud"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class DeliveryStatus(str, Enum):
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class MediaType(str, Enum):
    """
    Type of the attached media payload.

    WAHA mapping:
      "image"    → IMAGE
      "audio"    → AUDIO
      "ptt"      → AUDIO  (push-to-talk / voice note)
      "video"    → VIDEO
      "document" → DOCUMENT
      "sticker"  → STICKER

    Meta mapping:
      "image" / "audio" / "video" / "document" / "sticker" → direct
    """
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    STICKER = "sticker"


# ---------------------------------------------------------------------------
# Unified text / media message
# ---------------------------------------------------------------------------

class UnifiedMessage(BaseModel):
    """
    A single normalised representation of a WhatsApp message,
    regardless of which provider or media type delivered it.

    Text messages: set `body`, leave all `media_*` fields None.
    Media messages: set `media_type` + at least one of `media_id` / `media_url`.
                    Use `body` for the optional caption.
    """

    event_type: str = Field("message", description="Always 'message' for this model.")

    message_id: str = Field(..., description="Provider-assigned message ID.")

    from_number: str = Field(..., description="Sender's WhatsApp number (E.164, no '+').")
    to_number: str = Field(..., description="Recipient's WhatsApp number (E.164, no '+').")

    body: str = Field("", description="Plain-text body or media caption.")

    timestamp: datetime = Field(..., description="UTC send time.")
    provider: ChannelProvider = Field(...)
    direction: MessageDirection = Field(MessageDirection.INBOUND)

    # Optional metadata
    contact_name: Optional[str] = Field(None, description="Sender display name.")

    # ── Media fields (None for plain text messages) ──────────────────────────
    media_type: Optional[MediaType] = Field(
        None,
        description="Set when the message carries an image, audio, video, document, or sticker.",
    )
    media_id: Optional[str] = Field(
        None,
        description=(
            "Provider-assigned media object ID.  "
            "For Meta: use this with the Media API to get a download URL.  "
            "For WAHA: use mediaUrl directly."
        ),
    )
    media_url: Optional[str] = Field(
        None,
        description="Direct download URL (WAHA only; Meta requires a separate API call).",
    )
    media_mime_type: Optional[str] = Field(
        None,
        description="MIME type of the media, e.g. 'image/jpeg', 'application/pdf'.",
    )
    media_filename: Optional[str] = Field(
        None,
        description="Original filename (documents only).",
    )

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Unified read receipt
# ---------------------------------------------------------------------------

class UnifiedReadReceipt(BaseModel):
    """
    A normalised read / delivery receipt for a previously sent message.
    """

    event_type: str = Field("read_receipt", description="Always 'read_receipt' for this model.")

    message_id: str = Field(..., description="ID of the message whose status changed.")
    from_number: str = Field(..., description="Customer number that sent the receipt.")
    to_number: str = Field(..., description="Business number that sent the original message.")

    status: DeliveryStatus = Field(...)
    timestamp: datetime = Field(...)
    provider: ChannelProvider = Field(...)

    class Config:
        use_enum_values = True
