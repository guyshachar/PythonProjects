"""
StateManager – persists and transitions the routing channel state in Redis.

State machine:

    NORMAL ──(ban detected)──► BANNED ──(ban expired + WAHA probe OK)──► NORMAL
                                  │
                                  └──(ban expired + WAHA probe FAIL)──► BANNED (reset TTL)

States:
  NORMAL  – primary channel (WAHA) is operational; all messages go via WAHA.
  BANNED  – WAHA number is suspended; all messages route via Meta Cloud API.

Persistence layout (Redis hash):
  Key:   routing:state:{session_id}
  Fields:
    state       – "normal" | "banned"
    banned_at   – ISO-8601 UTC timestamp of when the ban was detected
    expires_at  – ISO-8601 UTC timestamp after which we probe for recovery
                  (banned_at + BAN_TTL_SECONDS)

The key has NO Redis TTL – state must survive app restarts and is only
changed by explicit transitions.

Ban TTL: configurable via BAN_RECOVERY_SECONDS env var (default 24h = 86400s).
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.services.redis_client import RedisClient

logger = logging.getLogger(__name__)

_KEY_PREFIX = "routing:state:"
_DEFAULT_BAN_TTL: int = int(os.environ.get("BAN_RECOVERY_SECONDS", 86400))  # 24 h


class ChannelState(str, Enum):
    NORMAL = "normal"
    BANNED = "banned"


class StateManager:
    """
    Thread-safe (async) routing state manager backed by Redis.

    One StateManager instance is shared across all requests via app.state.
    """

    def __init__(self, redis: RedisClient, ban_ttl_seconds: int = _DEFAULT_BAN_TTL) -> None:
        self._redis = redis
        self._ban_ttl = ban_ttl_seconds

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def get_state(self, session_id: str = "default") -> ChannelState:
        """Return the current state for the given WAHA session."""
        raw = await self._redis._client.get(self._key(session_id))
        if raw is None:
            # First run: no state stored yet, default to NORMAL.
            return ChannelState.NORMAL

        data: dict = json.loads(raw)
        state_str: str = data.get("state", ChannelState.NORMAL.value)
        return ChannelState(state_str)

    async def get_state_data(self, session_id: str = "default") -> dict:
        """Return the full state payload (includes banned_at, expires_at)."""
        raw = await self._redis._client.get(self._key(session_id))
        if raw is None:
            return {"state": ChannelState.NORMAL.value}
        return json.loads(raw)

    async def set_banned(self, session_id: str = "default") -> None:
        """
        Transition to BANNED.

        Records banned_at (now) and expires_at (now + ban_ttl) so that
        RouterService knows when to start probing for recovery.
        """
        now = datetime.now(tz=timezone.utc)
        data = {
            "state": ChannelState.BANNED.value,
            "banned_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=self._ban_ttl)).isoformat(),
        }
        await self._redis._client.set(self._key(session_id), json.dumps(data))
        logger.warning(
            "StateManager: session '%s' → BANNED (expires_at=%s)",
            session_id,
            data["expires_at"],
        )

    async def set_normal(self, session_id: str = "default") -> None:
        """Transition back to NORMAL (called after a successful WAHA probe)."""
        data = {"state": ChannelState.NORMAL.value}
        await self._redis._client.set(self._key(session_id), json.dumps(data))
        logger.info("StateManager: session '%s' → NORMAL (recovered).", session_id)

    async def is_ban_expired(self, session_id: str = "default") -> bool:
        """
        Return True if the ban TTL has elapsed and it is safe to probe WAHA.

        If the state is not BANNED, always returns False.
        """
        data = await self.get_state_data(session_id)
        if data.get("state") != ChannelState.BANNED.value:
            return False

        expires_at_str: str | None = data.get("expires_at")
        if not expires_at_str:
            # Malformed record – allow probe.
            return True

        expires_at = datetime.fromisoformat(expires_at_str)
        return datetime.now(tz=timezone.utc) >= expires_at

    # -----------------------------------------------------------------------
    # Private
    # -----------------------------------------------------------------------

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{_KEY_PREFIX}{session_id}"
