"""
Unit tests for StateManager.

All tests use the fake_redis_client fixture (in-memory, no real Redis).
"""

import pytest
from datetime import datetime, timedelta, timezone

from app.services.state_manager import ChannelState, StateManager


pytestmark = pytest.mark.asyncio


class TestStateManagerDefaults:
    async def test_get_state_returns_normal_when_no_key(self, state_manager):
        """No Redis key → default to NORMAL."""
        state = await state_manager.get_state("default")
        assert state == ChannelState.NORMAL

    async def test_get_state_data_returns_dict_when_no_key(self, state_manager):
        data = await state_manager.get_state_data("default")
        assert data["state"] == ChannelState.NORMAL.value

    async def test_is_ban_expired_false_when_normal(self, state_manager):
        assert await state_manager.is_ban_expired("default") is False


class TestStateManagerBanned:
    async def test_set_banned_transitions_state(self, state_manager):
        await state_manager.set_banned("default")
        state = await state_manager.get_state("default")
        assert state == ChannelState.BANNED

    async def test_set_banned_stores_timestamps(self, state_manager):
        await state_manager.set_banned("default")
        data = await state_manager.get_state_data("default")
        assert "banned_at" in data
        assert "expires_at" in data

    async def test_set_banned_expires_at_is_future(self, state_manager):
        await state_manager.set_banned("default")
        data = await state_manager.get_state_data("default")
        expires_at = datetime.fromisoformat(data["expires_at"])
        assert expires_at > datetime.now(tz=timezone.utc)

    async def test_is_ban_expired_false_when_fresh_ban(self, state_manager):
        await state_manager.set_banned("default")
        # TTL is 3600s (fixture); a freshly set ban is not yet expired.
        assert await state_manager.is_ban_expired("default") is False


class TestStateManagerRecovery:
    async def test_set_normal_after_ban(self, state_manager):
        await state_manager.set_banned("default")
        await state_manager.set_normal("default")
        state = await state_manager.get_state("default")
        assert state == ChannelState.NORMAL

    async def test_is_ban_expired_true_when_ttl_elapsed(self, fake_redis_client):
        """Simulate an expired ban by writing a backdated expires_at directly."""
        import json
        past = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        data = {
            "state": ChannelState.BANNED.value,
            "banned_at": (past - timedelta(hours=1)).isoformat(),
            "expires_at": past.isoformat(),
        }
        await fake_redis_client._client.set("routing:state:default", json.dumps(data))
        sm = StateManager(redis=fake_redis_client, ban_ttl_seconds=3600)
        assert await sm.is_ban_expired("default") is True

    async def test_is_ban_expired_false_when_ttl_not_elapsed(self, fake_redis_client):
        import json
        future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
        data = {
            "state": ChannelState.BANNED.value,
            "banned_at": datetime.now(tz=timezone.utc).isoformat(),
            "expires_at": future.isoformat(),
        }
        await fake_redis_client._client.set("routing:state:default", json.dumps(data))
        sm = StateManager(redis=fake_redis_client, ban_ttl_seconds=3600)
        assert await sm.is_ban_expired("default") is False


class TestStateManagerMultiSession:
    async def test_sessions_are_independent(self, state_manager):
        await state_manager.set_banned("session_a")
        state_a = await state_manager.get_state("session_a")
        state_b = await state_manager.get_state("session_b")
        assert state_a == ChannelState.BANNED
        assert state_b == ChannelState.NORMAL
