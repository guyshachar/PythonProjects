"""
Unit tests for MessageRouter (the failover orchestrator).

WahaClient and MetaCloudClient are replaced with AsyncMock so no real
HTTP calls are made.  StateManager uses the fake Redis fixture.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import json

from app.clients.base import BanDetectedError, ProviderError
from app.models.outbound import SendMessageRequest, SendMessageResponse
from app.models.unified import ChannelProvider
from app.services.router_service import MessageRouter
from app.services.state_manager import ChannelState, StateManager


pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def waha_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.send_text = AsyncMock(return_value="waha-msg-001")
    mock.health_check = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def meta_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.send_text = AsyncMock(return_value="meta-msg-001")
    mock.send_failover_template = AsyncMock(return_value="meta-tmpl-001")
    mock.send_template = AsyncMock(return_value="meta-tmpl-002")
    return mock


@pytest.fixture
def router(waha_mock, meta_mock, state_manager, fake_redis_client) -> MessageRouter:
    return MessageRouter(
        waha=waha_mock,
        meta=meta_mock,
        state_manager=state_manager,
        redis=fake_redis_client,
    )


@pytest.fixture
def send_request() -> SendMessageRequest:
    return SendMessageRequest(to="15551234567", body="Hello!", session_id="default")


# ---------------------------------------------------------------------------
# Normal state – routes via WAHA
# ---------------------------------------------------------------------------

class TestNormalState:
    async def test_send_via_waha_when_normal(self, router, waha_mock, send_request):
        response = await router.send(send_request)

        waha_mock.send_text.assert_awaited_once_with(
            to="15551234567", body="Hello!", session_id="default"
        )
        assert response.provider == ChannelProvider.WAHA
        assert response.message_id == "waha-msg-001"
        assert response.failover_triggered is False
        assert response.channel_state == ChannelState.NORMAL.value

    async def test_waha_provider_error_is_propagated(self, router, waha_mock, send_request):
        waha_mock.send_text.side_effect = ProviderError("timeout")
        with pytest.raises(ProviderError):
            await router.send(send_request)

    async def test_provider_error_does_not_trigger_failover(
        self, router, waha_mock, meta_mock, state_manager, send_request
    ):
        waha_mock.send_text.side_effect = ProviderError("5xx")
        with pytest.raises(ProviderError):
            await router.send(send_request)

        meta_mock.send_text.assert_not_awaited()
        meta_mock.send_failover_template.assert_not_awaited()
        assert await state_manager.get_state("default") == ChannelState.NORMAL


# ---------------------------------------------------------------------------
# Ban detection → automatic failover
# ---------------------------------------------------------------------------

class TestBanDetection:
    async def test_ban_triggers_failover_to_meta_template(
        self, router, waha_mock, meta_mock, state_manager, send_request
    ):
        waha_mock.send_text.side_effect = BanDetectedError("HTTP 403")

        response = await router.send(send_request)

        # State must transition to BANNED.
        assert await state_manager.get_state("default") == ChannelState.BANNED

        # Meta template was used (no conversation window exists).
        meta_mock.send_failover_template.assert_awaited_once_with(to="15551234567")

        assert response.provider == ChannelProvider.META_CLOUD
        assert response.failover_triggered is True
        assert response.channel_state == ChannelState.BANNED.value

    async def test_ban_with_active_conversation_window_uses_free_form(
        self, router, waha_mock, meta_mock, state_manager, fake_redis_client, send_request
    ):
        # Simulate an active conversation window.
        await fake_redis_client._client.set(
            "meta:conv_window:15551234567", "1", ex=86400
        )
        waha_mock.send_text.side_effect = BanDetectedError("HTTP 401")

        response = await router.send(send_request)

        # Free-form text, not template.
        meta_mock.send_text.assert_awaited_once_with(to="15551234567", body="Hello!")
        meta_mock.send_failover_template.assert_not_awaited()
        assert response.failover_triggered is True

    async def test_ban_with_custom_template_override(
        self, router, waha_mock, meta_mock, state_manager, send_request
    ):
        send_request.template_name = "promo_alert"
        send_request.template_language = "he"
        waha_mock.send_text.side_effect = BanDetectedError("HTTP 403")

        await router.send(send_request)

        meta_mock.send_template.assert_awaited_once_with(
            to="15551234567",
            template_name="promo_alert",
            language_code="he",
        )


# ---------------------------------------------------------------------------
# Already-banned state routing
# ---------------------------------------------------------------------------

class TestBannedState:
    async def test_routes_to_meta_when_already_banned(
        self, router, waha_mock, meta_mock, state_manager, send_request
    ):
        await state_manager.set_banned("default")

        response = await router.send(send_request)

        waha_mock.send_text.assert_not_awaited()
        assert response.provider == ChannelProvider.META_CLOUD
        assert response.failover_triggered is False


# ---------------------------------------------------------------------------
# Recovery probe
# ---------------------------------------------------------------------------

class TestRecoveryProbe:
    async def _set_expired_ban(self, fake_redis_client):
        """Write a ban record with an expires_at in the past."""
        past = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        data = {
            "state": ChannelState.BANNED.value,
            "banned_at": (past - timedelta(hours=1)).isoformat(),
            "expires_at": past.isoformat(),
        }
        await fake_redis_client._client.set(
            "routing:state:default", json.dumps(data)
        )

    async def test_recovery_probe_success_switches_to_normal(
        self, router, waha_mock, meta_mock, state_manager, fake_redis_client, send_request
    ):
        await self._set_expired_ban(fake_redis_client)
        waha_mock.health_check.return_value = True

        response = await router.send(send_request)

        # WAHA probe was called.
        waha_mock.health_check.assert_awaited_once_with("default")

        # WAHA delivery was used after recovery.
        waha_mock.send_text.assert_awaited_once()
        meta_mock.send_text.assert_not_awaited()
        meta_mock.send_failover_template.assert_not_awaited()

        assert response.provider == ChannelProvider.WAHA
        assert await state_manager.get_state("default") == ChannelState.NORMAL

    async def test_recovery_probe_failure_stays_on_meta(
        self, router, waha_mock, meta_mock, state_manager, fake_redis_client, send_request
    ):
        await self._set_expired_ban(fake_redis_client)
        waha_mock.health_check.return_value = False

        response = await router.send(send_request)

        waha_mock.health_check.assert_awaited_once()
        waha_mock.send_text.assert_not_awaited()

        assert response.provider == ChannelProvider.META_CLOUD
        # Ban TTL was reset (state still BANNED).
        assert await state_manager.get_state("default") == ChannelState.BANNED

    async def test_recovery_ban_expired_but_waha_fails_again_triggers_new_ban(
        self, router, waha_mock, meta_mock, state_manager, fake_redis_client, send_request
    ):
        """
        Edge case: ban expired → WAHA probe passes → send via WAHA →
        but WAHA raises BanDetectedError again (still banned).
        Should re-ban and fall back to Meta.
        """
        await self._set_expired_ban(fake_redis_client)
        waha_mock.health_check.return_value = True
        waha_mock.send_text.side_effect = BanDetectedError("still banned")

        response = await router.send(send_request)

        assert await state_manager.get_state("default") == ChannelState.BANNED
        assert response.provider == ChannelProvider.META_CLOUD
        assert response.failover_triggered is True


# ---------------------------------------------------------------------------
# Conversation window
# ---------------------------------------------------------------------------

class TestConversationWindow:
    async def test_mark_conversation_window(self, router, fake_redis_client):
        await router.mark_conversation_window("15551234567")
        val = await fake_redis_client._client.get("meta:conv_window:15551234567")
        assert val == "1"

    async def test_has_conversation_window_true(self, router, fake_redis_client):
        await fake_redis_client._client.set("meta:conv_window:15551234567", "1", ex=3600)
        assert await router._has_conversation_window("15551234567") is True

    async def test_has_conversation_window_false(self, router):
        assert await router._has_conversation_window("99999999999") is False
