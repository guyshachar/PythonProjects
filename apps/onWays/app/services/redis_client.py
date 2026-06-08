"""
Redis wrapper for idempotency checks.

Every inbound webhook carries a message_id.  Before processing we check
whether we have already handled this ID.  If yes, we return a 200 OK
immediately without re-emitting the event (prevents duplicate CRM entries
when providers retry delivery).

Key design choices:
  - TTL defaults to 24 hours – long enough to catch any provider retry window.
  - The key namespace is "idempotency:<message_id>" to avoid collisions.
  - Uses a simple SET NX (set if not exists) operation so the mark and check
    are a single atomic round-trip.
"""

import os
from typing import Optional

import redis.asyncio as aioredis

# Default TTL: 24 hours in seconds.
_DEFAULT_TTL: int = 60 * 60 * 24
_KEY_PREFIX: str = "idempotency:"


class RedisClient:
    """Thin async wrapper around redis.asyncio."""

    def __init__(self, url: Optional[str] = None, ttl: int = _DEFAULT_TTL) -> None:
        redis_url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._client = aioredis.from_url(redis_url, decode_responses=True)
        self._ttl = ttl

    async def is_duplicate(self, message_id: str) -> bool:
        """
        Return True if this message_id has been seen before.

        Uses SET NX EX so the check and mark are a single atomic operation,
        meaning there is no TOCTOU race even under concurrent requests.
        """
        key = f"{_KEY_PREFIX}{message_id}"
        # SET key value NX EX ttl  →  returns True if the key was NEW (set),
        # returns None/False if it already existed.
        was_set = await self._client.set(key, "1", nx=True, ex=self._ttl)
        # was_set is True  → first time we see this ID → NOT a duplicate
        # was_set is None  → key already existed      → IS  a duplicate
        return was_set is None

    async def close(self) -> None:
        await self._client.aclose()
