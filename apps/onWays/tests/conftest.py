"""
Shared pytest fixtures for OnWays gateway tests.

Fake Redis
──────────
Uses fakeredis.aioredis to provide an in-memory Redis backend.
Each test gets a fresh instance (function-scoped) so state never leaks.

The fixture patches RedisClient._client directly to avoid needing a real
Redis server.  All other services (StateManager, MessageRouter) are
constructed with this fake client.
"""

import pytest
import fakeredis.aioredis as fake_aioredis

from app.services.redis_client import RedisClient
from app.services.state_manager import StateManager
from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_redis_client() -> RedisClient:
    """
    A RedisClient whose internal _client is backed by fakeredis.
    Function-scoped: every test starts with a clean in-memory store.
    """
    client = RedisClient.__new__(RedisClient)
    client._client = fake_aioredis.FakeRedis(decode_responses=True)
    client._ttl = 86400
    return client


@pytest.fixture
def state_manager(fake_redis_client: RedisClient) -> StateManager:
    """StateManager wired to the fake Redis client."""
    return StateManager(redis=fake_redis_client, ban_ttl_seconds=3600)


# ---------------------------------------------------------------------------
# Settings cache
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    Clear the lru_cache on get_settings before each test so env-var
    overrides in tests take effect immediately.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
