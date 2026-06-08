"""
CrmForwarder – forwards normalised webhook events to the downstream CRM.

Reliability improvements (Phase 4)
────────────────────────────────────
Retry with exponential back-off
  Up to CRM_MAX_RETRIES attempts (default 3).
  Delays: 1 s, 2 s, 4 s, … (2^(attempt-1) seconds).
  Retries on network errors AND on 4xx/5xx responses from the CRM.

Redis dead-letter queue
  When all retries are exhausted, the failed event is appended to a Redis
  list (key: crm:dead_letter) as a JSON object that includes the event, the
  last error, and a UTC timestamp.  The list is capped at 200 entries (oldest
  drop off).  The admin endpoint exposes this queue for inspection/replay.

Optional HMAC signature
  If CRM_WEBHOOK_SECRET is set, every POST carries
  X-Onways-Signature: sha256=<hex> so the CRM can verify authenticity.

If CRM_WEBHOOK_URL is blank, the entire forward operation is a no-op.
"""

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Union

import httpx

from app.models.unified import UnifiedMessage, UnifiedReadReceipt

logger = logging.getLogger(__name__)

ForwardableEvent = Union[UnifiedMessage, UnifiedReadReceipt]

_DEAD_LETTER_KEY = "crm:dead_letter"
_DEAD_LETTER_MAX = 200


class CrmForwarder:
    """
    Async HTTP forwarder with retry and Redis dead-letter queue.

    Parameters (injected from Settings at startup):
      crm_webhook_url    – destination URL (POST)
      crm_webhook_secret – optional HMAC secret for X-Onways-Signature
      max_retries        – number of attempts (default 3)
      redis_client       – optional RedisClient for dead-letter storage
    """

    def __init__(
        self,
        crm_webhook_url: str = "",
        crm_webhook_secret: str = "",
        max_retries: int = 3,
        redis_client=None,          # app.services.redis_client.RedisClient
    ) -> None:
        self._url = crm_webhook_url
        self._secret = crm_webhook_secret
        self._max_retries = max(1, max_retries)
        self._redis = redis_client

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def forward(self, event: ForwardableEvent) -> None:
        """
        POST the serialised event to the CRM webhook URL with retries.

        Swallows all exceptions after exhausting retries and writes to
        dead-letter instead.  The provider always receives a 200.
        """
        if not self._url:
            logger.debug("CrmForwarder: CRM_WEBHOOK_URL not set – skipping forward.")
            return

        body: bytes = json.dumps(
            event.model_dump(mode="json"), default=str
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Onways-Event": event.event_type,
        }
        if self._secret:
            headers["X-Onways-Signature"] = self._compute_signature(body)

        last_error: str = ""

        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(self._url, content=body, headers=headers)

                if response.status_code < 400:
                    logger.debug(
                        "CrmForwarder: forwarded %s message_id=%s (attempt %d) → %d",
                        event.event_type, event.message_id, attempt, response.status_code,
                    )
                    return  # success

                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.warning(
                    "CrmForwarder: CRM returned %d (attempt %d/%d) for message_id=%s: %s",
                    response.status_code, attempt, self._max_retries,
                    event.message_id, response.text[:100],
                )

            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "CrmForwarder: network error (attempt %d/%d) for message_id=%s: %s",
                    attempt, self._max_retries, event.message_id, exc,
                )

            # Back-off before the next retry (skip sleep after the last attempt).
            if attempt < self._max_retries:
                await asyncio.sleep(2 ** (attempt - 1))   # 1 s, 2 s, 4 s …

        # All retries exhausted → dead-letter.
        logger.error(
            "CrmForwarder: all %d attempts failed for message_id=%s – writing to dead-letter.",
            self._max_retries, event.message_id,
        )
        await self._write_dead_letter(event, last_error)

    async def get_dead_letter_entries(self, limit: int = 50) -> list[dict]:
        """
        Return the most recent `limit` dead-letter entries (newest first).
        Returns [] if Redis is not configured or the queue is empty.
        """
        if not self._redis:
            return []
        raw_list = await self._redis._client.lrange(_DEAD_LETTER_KEY, 0, limit - 1)
        entries = []
        for raw in raw_list:
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return entries

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _write_dead_letter(self, event: ForwardableEvent, error: str) -> None:
        if not self._redis:
            logger.error(
                "CrmForwarder [DEAD_LETTER] message_id=%s event_type=%s error=%s",
                event.message_id, event.event_type, error,
            )
            return

        entry = {
            "message_id": event.message_id,
            "event_type": event.event_type,
            "error": error,
            "failed_at": datetime.now(tz=timezone.utc).isoformat(),
            "payload": event.model_dump(mode="json", exclude_none=True),
        }
        try:
            pipe = self._redis._client.pipeline()
            pipe.lpush(_DEAD_LETTER_KEY, json.dumps(entry, default=str))
            pipe.ltrim(_DEAD_LETTER_KEY, 0, _DEAD_LETTER_MAX - 1)
            await pipe.execute()
            logger.info(
                "CrmForwarder: wrote message_id=%s to Redis dead-letter queue.",
                event.message_id,
            )
        except Exception as exc:
            logger.error("CrmForwarder: could not write dead-letter entry: %s", exc)

    def _compute_signature(self, body: bytes) -> str:
        digest = hmac.new(
            self._secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return f"sha256={digest}"
