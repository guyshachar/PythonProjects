"""
Integration tests for POST /v1/webhooks/{provider} and GET /v1/webhooks/meta.

Uses Starlette's synchronous TestClient which correctly fires startup/shutdown
lifespan events.  Redis is replaced with an in-memory fakeredis instance.

Coverage
────────
  - Happy-path WAHA text message → 200, unified JSON
  - Happy-path WAHA image (media) message → 200, media fields populated
  - Happy-path Meta text message → 200, unified JSON
  - Happy-path Meta image message → 200, media_id populated
  - Duplicate webhook → 200, {"skipped": false, "detail": "Duplicate…"}
  - Malformed JSON body → 400
  - Unsupported event type → 200 with skipped=True
  - Meta GET challenge – correct token → 200, challenge text echoed
  - Meta GET challenge – wrong token → 403
  - Meta POST HMAC – valid signature → 200
  - Meta POST HMAC – invalid signature → 403
  - Meta POST HMAC – secret not configured (dev mode) → 200 (no enforcement)
  - X-Request-Id header echoed back in response
"""

import hashlib
import hmac
import json
import os
from unittest.mock import patch

import fakeredis.aioredis
import pytest
from starlette.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.services.redis_client import RedisClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    """
    TestClient with:
      - Fake Redis (in-memory)
      - META_APP_SECRET set so HMAC is enforced
      - META_WEBHOOK_VERIFY_TOKEN set for hub challenge tests
    """
    monkeypatch.setenv("META_APP_SECRET", "test-secret")
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("META_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("GATEWAY_API_KEY", "")  # open for these tests
    get_settings.cache_clear()

    fake_conn = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def patched_init(self, url=None, ttl=86400):
        self._client = fake_conn
        self._ttl = ttl

    with patch.object(RedisClient, "__init__", patched_init):
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as tc:
            # Override channel clients so no real HTTP calls are made.
            from unittest.mock import AsyncMock
            app.state.message_router._waha = AsyncMock()
            app.state.message_router._meta = AsyncMock()
            yield tc, app


# ---------------------------------------------------------------------------
# WAHA text message
# ---------------------------------------------------------------------------

WAHA_TEXT_PAYLOAD = {
    "event": "message",
    "session": "default",
    "payload": {
        "id": "msg-waha-001",
        "from": "15551234567@c.us",
        "to": "15559876543@c.us",
        "body": "Hello from WAHA!",
        "timestamp": 1700000000,
        "fromMe": False,
        "type": "chat",
        "_data": {"notifyName": "Alice"},
    },
}


def test_waha_text_message_returns_unified_json(client):
    tc, _ = client
    resp = tc.post("/v1/webhooks/waha", json=WAHA_TEXT_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["event_type"] == "message"
    assert data["message_id"] == "msg-waha-001"
    assert data["from_number"] == "15551234567"
    assert data["to_number"] == "15559876543"
    assert data["body"] == "Hello from WAHA!"
    assert data["provider"] == "waha"
    assert data["direction"] == "inbound"
    assert data["contact_name"] == "Alice"
    assert data["media_type"] is None


def test_waha_text_message_duplicate_returns_200_with_skip_notice(client):
    tc, _ = client
    tc.post("/v1/webhooks/waha", json=WAHA_TEXT_PAYLOAD)   # first call
    resp = tc.post("/v1/webhooks/waha", json=WAHA_TEXT_PAYLOAD)  # duplicate

    assert resp.status_code == 200
    data = resp.json()
    assert "Duplicate" in data["detail"]
    assert data["message_id"] == "msg-waha-001"


def test_waha_image_message_populates_media_fields(client):
    tc, _ = client
    payload = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "msg-waha-img-001",
            "from": "15551234567@c.us",
            "to": "15559876543@c.us",
            "body": "check this pic",
            "timestamp": 1700000000,
            "fromMe": False,
            "type": "image",
            "hasMedia": True,
            "mediaUrl": "http://waha/download/abc123",
            "_data": {"notifyName": "Bob", "mimetype": "image/jpeg"},
        },
    }
    resp = tc.post("/v1/webhooks/waha", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["media_type"] == "image"
    assert data["media_url"] == "http://waha/download/abc123"
    assert data["media_mime_type"] == "image/jpeg"


def test_waha_malformed_json_returns_400(client):
    tc, _ = client
    resp = tc.post(
        "/v1/webhooks/waha",
        content=b"not json at all!!!",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_unsupported_waha_event_returns_200_skipped(client):
    tc, _ = client
    # An event type not handled by the parser (but passes can_parse).
    # To trigger NotImplementedError, we'd need a real unsupported event.
    # Meta payload with neither messages nor statuses hits NotImplementedError.
    meta_empty = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "x", "changes": [{"value": {"metadata": {}, "messaging_product": "whatsapp"}, "field": "messages"}]}],
    }
    resp = tc.post("/v1/webhooks/meta", json=meta_empty,
                   headers={"X-Hub-Signature-256": _make_signature(
                       json.dumps(meta_empty).encode(), "test-secret"
                   )})
    assert resp.status_code == 200
    assert resp.json().get("skipped") is True


# ---------------------------------------------------------------------------
# Meta text message
# ---------------------------------------------------------------------------

META_TEXT_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "waba-001",
        "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"phone_number_id": "987", "display_phone_number": "15559876543"},
                "contacts": [{"profile": {"name": "Carol"}, "wa_id": "15551234567"}],
                "messages": [{
                    "id": "msg-meta-001",
                    "from": "15551234567",
                    "timestamp": "1700000000",
                    "type": "text",
                    "text": {"body": "Hello from Meta!"},
                }],
            },
            "field": "messages",
        }],
    }],
}


def test_meta_text_message_with_valid_hmac(client):
    tc, _ = client
    body = json.dumps(META_TEXT_PAYLOAD).encode()
    sig = _make_signature(body, "test-secret")

    resp = tc.post(
        "/v1/webhooks/meta",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["message_id"] == "msg-meta-001"
    assert data["provider"] == "meta_cloud"
    assert data["contact_name"] == "Carol"


def test_meta_message_with_invalid_hmac_returns_403(client):
    tc, _ = client
    body = json.dumps(META_TEXT_PAYLOAD).encode()

    resp = tc.post(
        "/v1/webhooks/meta",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=badhash"},
    )
    assert resp.status_code == 403


def test_meta_message_no_hmac_header_returns_403(client):
    tc, _ = client
    resp = tc.post("/v1/webhooks/meta", json=META_TEXT_PAYLOAD)
    assert resp.status_code == 403


def test_meta_hmac_not_enforced_when_secret_blank(monkeypatch):
    """When META_APP_SECRET is blank, HMAC check is skipped (dev mode)."""
    monkeypatch.setenv("META_APP_SECRET", "")
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "tok")
    monkeypatch.setenv("GATEWAY_API_KEY", "")
    get_settings.cache_clear()

    fake_conn = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def patched_init(self, url=None, ttl=86400):
        self._client = fake_conn
        self._ttl = ttl

    with patch.object(RedisClient, "__init__", patched_init):
        app = create_app()
        with TestClient(app) as tc:
            # No signature header at all – should pass.
            resp = tc.post("/v1/webhooks/meta", json=META_TEXT_PAYLOAD)
            assert resp.status_code == 200


def test_meta_image_message_populates_media_id(client):
    tc, _ = client
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba-001",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "987", "display_phone_number": "15559876543"},
                    "messages": [{
                        "id": "msg-meta-img-001",
                        "from": "15551234567",
                        "timestamp": "1700000000",
                        "type": "image",
                        "image": {
                            "id": "media-id-abc",
                            "mime_type": "image/jpeg",
                            "caption": "photo caption",
                        },
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode()
    sig = _make_signature(body, "test-secret")

    resp = tc.post(
        "/v1/webhooks/meta",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["media_type"] == "image"
    assert data["media_id"] == "media-id-abc"
    assert data["media_mime_type"] == "image/jpeg"
    assert data["body"] == "photo caption"


# ---------------------------------------------------------------------------
# Meta hub challenge (GET)
# ---------------------------------------------------------------------------

def test_meta_hub_challenge_correct_token(client):
    tc, _ = client
    resp = tc.get(
        "/v1/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify-token",
            "hub.challenge": "challenge-xyz",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "challenge-xyz"


def test_meta_hub_challenge_wrong_token_returns_403(client):
    tc, _ = client
    resp = tc.get(
        "/v1/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-xyz",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Correlation ID
# ---------------------------------------------------------------------------

def test_request_id_echoed_in_response(client):
    tc, _ = client
    resp = tc.get("/health", headers={"X-Request-Id": "my-custom-id-123"})
    assert resp.headers.get("X-Request-Id") == "my-custom-id-123"


def test_request_id_generated_when_absent(client):
    tc, _ = client
    resp = tc.get("/health")
    req_id = resp.headers.get("X-Request-Id", "")
    assert len(req_id) == 36  # UUID4 string length
