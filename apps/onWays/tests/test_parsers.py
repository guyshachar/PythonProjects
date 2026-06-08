"""
Unit tests for WahaWebhookParser and MetaCloudWebhookParser.

Tests cover:
  - can_parse(): true for valid payloads, false for foreign payloads
  - parse(): happy-path for message and ack/status events
  - parse(): raises ValueError on missing required fields
  - parse(): raises NotImplementedError for unsupported event/message types
"""

import pytest
from datetime import timezone

from app.models.unified import (
    ChannelProvider,
    DeliveryStatus,
    MessageDirection,
    UnifiedMessage,
    UnifiedReadReceipt,
)
from app.parsers.waha import WahaWebhookParser
from app.parsers.meta import MetaCloudWebhookParser


# ============================================================================
# Fixtures – canonical raw payloads
# ============================================================================

@pytest.fixture
def waha_message_payload() -> dict:
    return {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "false_15551234567@c.us_ABC123",
            "from": "15551234567@c.us",
            "to": "15559876543@c.us",
            "body": "Hello, world!",
            "timestamp": 1700000000,
            "fromMe": False,
            "_data": {"notifyName": "Alice"},
        },
    }


@pytest.fixture
def waha_ack_payload() -> dict:
    return {
        "event": "message.ack",
        "session": "default",
        "payload": {
            "id": "false_15551234567@c.us_ABC123",
            "from": "15551234567@c.us",
            "to": "15559876543@c.us",
            "timestamp": 1700000100,
            "ack": 3,   # READ
        },
    }


@pytest.fixture
def meta_message_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": "987654321",
                        "display_phone_number": "15559876543",
                    },
                    "contacts": [{"profile": {"name": "Bob"}, "wa_id": "15551234567"}],
                    "messages": [{
                        "id": "wamid.HBgLM1VUBQ==",
                        "from": "15551234567",
                        "timestamp": "1700000000",
                        "type": "text",
                        "text": {"body": "Hi there!"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }


@pytest.fixture
def meta_status_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "phone_number_id": "987654321",
                        "display_phone_number": "15559876543",
                    },
                    "statuses": [{
                        "id": "wamid.HBgLM1VUBQ==",
                        "recipient_id": "15551234567",
                        "status": "read",
                        "timestamp": "1700000200",
                    }],
                },
                "field": "messages",
            }],
        }],
    }


# ============================================================================
# WahaWebhookParser
# ============================================================================

class TestWahaWebhookParser:
    parser = WahaWebhookParser()

    # -- can_parse ------------------------------------------------------------

    def test_can_parse_message(self, waha_message_payload):
        assert self.parser.can_parse(waha_message_payload) is True

    def test_can_parse_ack(self, waha_ack_payload):
        assert self.parser.can_parse(waha_ack_payload) is True

    def test_cannot_parse_meta(self, meta_message_payload):
        assert self.parser.can_parse(meta_message_payload) is False

    def test_cannot_parse_empty(self):
        assert self.parser.can_parse({}) is False

    def test_cannot_parse_unknown_event(self):
        assert self.parser.can_parse({"event": "status.update", "session": "x"}) is False

    # -- parse message --------------------------------------------------------

    def test_parse_message_fields(self, waha_message_payload):
        result = self.parser.parse(waha_message_payload)

        assert isinstance(result, UnifiedMessage)
        assert result.message_id == "false_15551234567@c.us_ABC123"
        assert result.from_number == "15551234567"
        assert result.to_number == "15559876543"
        assert result.body == "Hello, world!"
        assert result.provider == ChannelProvider.WAHA
        assert result.direction == MessageDirection.INBOUND
        assert result.contact_name == "Alice"
        assert result.timestamp.tzinfo == timezone.utc

    def test_parse_message_from_me(self, waha_message_payload):
        waha_message_payload["payload"]["fromMe"] = True
        result = self.parser.parse(waha_message_payload)
        assert result.direction == MessageDirection.OUTBOUND

    def test_parse_message_no_notify_name(self, waha_message_payload):
        del waha_message_payload["payload"]["_data"]
        result = self.parser.parse(waha_message_payload)
        assert result.contact_name is None

    def test_parse_message_missing_id_raises(self, waha_message_payload):
        del waha_message_payload["payload"]["id"]
        with pytest.raises(ValueError, match="missing required field"):
            self.parser.parse(waha_message_payload)

    def test_parse_missing_payload_raises(self, waha_message_payload):
        del waha_message_payload["payload"]
        with pytest.raises(ValueError, match="missing 'payload'"):
            self.parser.parse(waha_message_payload)

    # -- parse ack ------------------------------------------------------------

    def test_parse_ack_read(self, waha_ack_payload):
        result = self.parser.parse(waha_ack_payload)

        assert isinstance(result, UnifiedReadReceipt)
        assert result.message_id == "false_15551234567@c.us_ABC123"
        assert result.status == DeliveryStatus.READ
        assert result.provider == ChannelProvider.WAHA

    def test_parse_ack_delivered(self, waha_ack_payload):
        waha_ack_payload["payload"]["ack"] = 2
        result = self.parser.parse(waha_ack_payload)
        assert result.status == DeliveryStatus.DELIVERED

    def test_parse_ack_unknown_code_defaults_to_sent(self, waha_ack_payload):
        waha_ack_payload["payload"]["ack"] = 99
        result = self.parser.parse(waha_ack_payload)
        assert result.status == DeliveryStatus.SENT

    def test_parse_ack_missing_ack_field_raises(self, waha_ack_payload):
        del waha_ack_payload["payload"]["ack"]
        with pytest.raises(ValueError, match="missing required field"):
            self.parser.parse(waha_ack_payload)


# ============================================================================
# MetaCloudWebhookParser
# ============================================================================

class TestMetaCloudWebhookParser:
    parser = MetaCloudWebhookParser()

    # -- can_parse ------------------------------------------------------------

    def test_can_parse_message(self, meta_message_payload):
        assert self.parser.can_parse(meta_message_payload) is True

    def test_can_parse_status(self, meta_status_payload):
        assert self.parser.can_parse(meta_status_payload) is True

    def test_cannot_parse_waha(self, waha_message_payload):
        assert self.parser.can_parse(waha_message_payload) is False

    def test_cannot_parse_empty(self):
        assert self.parser.can_parse({}) is False

    # -- parse message --------------------------------------------------------

    def test_parse_message_fields(self, meta_message_payload):
        result = self.parser.parse(meta_message_payload)

        assert isinstance(result, UnifiedMessage)
        assert result.message_id == "wamid.HBgLM1VUBQ=="
        assert result.from_number == "15551234567"
        assert result.to_number == "15559876543"
        assert result.body == "Hi there!"
        assert result.provider == ChannelProvider.META_CLOUD
        assert result.direction == MessageDirection.INBOUND
        assert result.contact_name == "Bob"
        assert result.timestamp.tzinfo == timezone.utc

    def test_parse_message_no_contacts(self, meta_message_payload):
        del meta_message_payload["entry"][0]["changes"][0]["value"]["contacts"]
        result = self.parser.parse(meta_message_payload)
        assert result.contact_name is None

    def test_parse_non_text_type_raises_not_implemented(self, meta_message_payload):
        # "image" / "audio" / "video" / "document" are now supported (Phase 4).
        # "reaction" and "contacts_array" are not.
        meta_message_payload["entry"][0]["changes"][0]["value"]["messages"][0]["type"] = "reaction"
        with pytest.raises(NotImplementedError, match="not yet supported"):
            self.parser.parse(meta_message_payload)

    def test_parse_missing_message_id_raises(self, meta_message_payload):
        del meta_message_payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
        with pytest.raises(ValueError, match="missing required field"):
            self.parser.parse(meta_message_payload)

    def test_parse_malformed_structure_raises(self):
        with pytest.raises(ValueError, match="unexpected structure"):
            self.parser.parse({"object": "whatsapp_business_account", "entry": []})

    # -- parse status ---------------------------------------------------------

    def test_parse_status_read(self, meta_status_payload):
        result = self.parser.parse(meta_status_payload)

        assert isinstance(result, UnifiedReadReceipt)
        assert result.message_id == "wamid.HBgLM1VUBQ=="
        assert result.from_number == "15551234567"
        assert result.status == DeliveryStatus.READ
        assert result.provider == ChannelProvider.META_CLOUD

    def test_parse_status_unknown_defaults_to_sent(self, meta_status_payload):
        meta_status_payload["entry"][0]["changes"][0]["value"]["statuses"][0]["status"] = "bizarre"
        result = self.parser.parse(meta_status_payload)
        assert result.status == DeliveryStatus.SENT

    def test_parse_neither_messages_nor_statuses_raises(self, meta_message_payload):
        del meta_message_payload["entry"][0]["changes"][0]["value"]["messages"]
        with pytest.raises(NotImplementedError):
            self.parser.parse(meta_message_payload)
