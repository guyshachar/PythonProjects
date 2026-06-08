"""
Integration tests for POST /v1/messages and /v1/admin/* endpoints.

Uses Starlette's synchronous TestClient with fake Redis.

Coverage
────────
Messages endpoint:
  - No API key → 401 (when GATEWAY_API_KEY is configured)
  - Wrong API key → 401
  - Valid key, NORMAL state → 200, WAHA used
  - Valid key, BANNED state → 200, Meta used, failover_triggered=False
  - Valid key, WAHA raises BanDetectedError → 200, failover_triggered=True
  - Both channels fail → 503

Admin endpoints:
  - GET /v1/admin/state/default → returns current state
  - POST /v1/admin/state/default/reset → transitions to NORMAL
  - POST /v1/admin/state/default/ban → transitions to BANNED
  - GET /v1/admin/dead-letter → returns dead-letter queue
  - GET /v1/admin/health → Redis ok + channel state
  - Admin endpoints require API key
"""

import json
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
from starlette.testclient import TestClient

from app.clients.base import BanDetectedError, ProviderError
from app.core.config import get_settings
from app.main import create_app
from app.services.redis_client import RedisClient
from app.services.state_manager import ChannelState

API_KEY = "integration-test-key-xyz"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_with_mocks(monkeypatch):
    """
    Full integration client:
      - GATEWAY_API_KEY enforced
      - Fake Redis
      - WahaClient / MetaCloudClient replaced by AsyncMock after startup
    """
    monkeypatch.setenv("GATEWAY_API_KEY", API_KEY)
    monkeypatch.setenv("META_APP_SECRET", "")          # skip HMAC for these tests
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "tok")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("META_ACCESS_TOKEN", "fake")
    get_settings.cache_clear()

    fake_conn = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def patched_init(self, url=None, ttl=86400):
        self._client = fake_conn
        self._ttl = ttl

    with patch.object(RedisClient, "__init__", patched_init):
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as tc:
            waha_mock = AsyncMock()
            waha_mock.send_text = AsyncMock(return_value="waha-int-001")
            waha_mock.health_check = AsyncMock(return_value=True)

            meta_mock = AsyncMock()
            meta_mock.send_failover_template = AsyncMock(return_value="meta-tmpl-int-001")
            meta_mock.send_text = AsyncMock(return_value="meta-free-int-001")

            app.state.message_router._waha = waha_mock
            app.state.message_router._meta = meta_mock

            yield tc, app, waha_mock, meta_mock


SEND_PAYLOAD = {"to": "15551234567", "body": "Hello integration!", "session_id": "default"}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_send_message_without_api_key_returns_401(client_with_mocks):
    tc, _, _, _ = client_with_mocks
    resp = tc.post("/v1/messages", json=SEND_PAYLOAD)
    assert resp.status_code == 401


def test_send_message_wrong_api_key_returns_401(client_with_mocks):
    tc, _, _, _ = client_with_mocks
    resp = tc.post("/v1/messages", json=SEND_PAYLOAD, headers={"X-Api-Key": "wrong-key"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Routing – NORMAL state
# ---------------------------------------------------------------------------

def test_send_message_normal_state_routes_via_waha(client_with_mocks):
    tc, _, waha_mock, meta_mock = client_with_mocks

    resp = tc.post("/v1/messages", json=SEND_PAYLOAD, headers={"X-Api-Key": API_KEY})

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "waha"
    assert data["message_id"] == "waha-int-001"
    assert data["failover_triggered"] is False
    assert data["channel_state"] == "normal"
    waha_mock.send_text.assert_awaited_once()
    meta_mock.send_failover_template.assert_not_awaited()


# ---------------------------------------------------------------------------
# Routing – BANNED state
# ---------------------------------------------------------------------------

def test_send_message_banned_state_routes_via_meta(client_with_mocks):
    tc, app, waha_mock, meta_mock = client_with_mocks

    # Force BANNED via the admin endpoint (runs inside TestClient's event loop).
    tc.post("/v1/admin/state/default/ban", headers={"X-Api-Key": API_KEY})

    resp = tc.post("/v1/messages", json=SEND_PAYLOAD, headers={"X-Api-Key": API_KEY})

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "meta_cloud"
    assert data["failover_triggered"] is False
    assert data["channel_state"] == "banned"
    waha_mock.send_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Failover on ban detection
# ---------------------------------------------------------------------------

def test_send_message_ban_detected_triggers_failover(client_with_mocks):
    tc, app, waha_mock, meta_mock = client_with_mocks

    waha_mock.send_text = AsyncMock(side_effect=BanDetectedError("HTTP 403"))

    resp = tc.post("/v1/messages", json=SEND_PAYLOAD, headers={"X-Api-Key": API_KEY})

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "meta_cloud"
    assert data["failover_triggered"] is True

    # Verify state transitioned to BANNED via the admin endpoint.
    state_resp = tc.get("/v1/admin/state/default", headers={"X-Api-Key": API_KEY})
    assert state_resp.json()["state"] == ChannelState.BANNED.value


def test_send_message_provider_error_returns_503(client_with_mocks):
    tc, _, waha_mock, _ = client_with_mocks
    waha_mock.send_text = AsyncMock(side_effect=ProviderError("timeout"))

    resp = tc.post("/v1/messages", json=SEND_PAYLOAD, headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Admin – state inspection and override
# ---------------------------------------------------------------------------

def test_admin_get_state_returns_normal_by_default(client_with_mocks):
    tc, _, _, _ = client_with_mocks
    resp = tc.get("/v1/admin/state/default", headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["state"] == "normal"


def test_admin_force_ban_then_reset(client_with_mocks):
    tc, _, _, _ = client_with_mocks

    # Force ban.
    resp = tc.post("/v1/admin/state/default/ban", headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["new_state"] == "banned"

    # Verify via GET.
    resp = tc.get("/v1/admin/state/default", headers={"X-Api-Key": API_KEY})
    assert resp.json()["state"] == "banned"
    assert resp.json()["banned_at"] is not None

    # Reset.
    resp = tc.post("/v1/admin/state/default/reset", headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["new_state"] == "normal"

    # Verify.
    resp = tc.get("/v1/admin/state/default", headers={"X-Api-Key": API_KEY})
    assert resp.json()["state"] == "normal"


def test_admin_requires_api_key(client_with_mocks):
    tc, _, _, _ = client_with_mocks
    resp = tc.get("/v1/admin/state/default")   # no X-Api-Key
    assert resp.status_code == 401


def test_admin_health_returns_ok(client_with_mocks):
    tc, _, _, _ = client_with_mocks
    resp = tc.get("/v1/admin/health", headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["redis"] == "ok"
    assert data["default_channel_state"] == "normal"


def test_admin_dead_letter_empty_by_default(client_with_mocks):
    tc, _, _, _ = client_with_mocks
    resp = tc.get("/v1/admin/dead-letter", headers={"X-Api-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    assert resp.json()["entries"] == []
