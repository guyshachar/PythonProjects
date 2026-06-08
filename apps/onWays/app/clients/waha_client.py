"""
WahaClient – outbound Strategy for the WAHA (WhatsApp HTTP API) unofficial wrapper.

Relevant WAHA API surface used here:
  POST /api/sendText              → send a text message
  GET  /api/sessions/{session_id} → probe session health

Ban detection heuristics:
  • HTTP 401 or 403 from any endpoint.
  • HTTP 422 with a body containing "ban" or "blocked".
  • HTTP 500 with a body containing "disconnected" (WAHA loses its WS to WhatsApp).

References:
  https://waha.devlike.pro/docs/how-to/send-messages/
  https://waha.devlike.pro/docs/how-to/sessions/
"""

import logging
import os

import httpx

from app.clients.base import BanDetectedError, IChannelClient, ProviderError

logger = logging.getLogger(__name__)

# HTTP status codes that definitively indicate a ban / auth revocation.
_BAN_STATUS_CODES: frozenset[int] = frozenset({401, 403})

# Substrings in the response body that also signal a ban when returned
# alongside a 422/500.
_BAN_BODY_SIGNALS: tuple[str, ...] = ("ban", "blocked", "disconnected", "unauthorized")


def _is_ban_response(status_code: int, body: str) -> bool:
    if status_code in _BAN_STATUS_CODES:
        return True
    if status_code in (422, 500):
        lower = body.lower()
        return any(sig in lower for sig in _BAN_BODY_SIGNALS)
    return False


class WahaClient(IChannelClient):
    """
    Sends WhatsApp messages via the WAHA HTTP sidecar.

    Configuration (via environment variables):
      WAHA_BASE_URL  – base URL of the WAHA container (default: http://localhost:3000)
      WAHA_API_KEY   – API key for WAHA (passed as X-Api-Key header; optional)
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._base_url = (base_url or os.environ.get("WAHA_BASE_URL", "http://localhost:3000")).rstrip("/")
        self._api_key = api_key or os.environ.get("WAHA_API_KEY", "")
        self._headers = {"X-Api-Key": self._api_key} if self._api_key else {}

    # -----------------------------------------------------------------------
    # IChannelClient interface
    # -----------------------------------------------------------------------

    async def send_text(self, to: str, body: str, session_id: str = "default") -> str:
        """
        POST /api/sendText

        WAHA expects chatId in '<number>@c.us' format.
        Returns the WAHA-assigned message ID.
        """
        chat_id = f"{to}@c.us" if "@" not in to else to
        payload = {"chatId": chat_id, "text": body, "session": session_id}

        async with httpx.AsyncClient(headers=self._headers, timeout=10.0) as client:
            try:
                response = await client.post(f"{self._base_url}/api/sendText", json=payload)
            except httpx.ConnectError as exc:
                # Cannot reach WAHA at all – treat as a potential ban/offline state.
                raise BanDetectedError(
                    f"WahaClient: connection error (WAHA may be down or banned): {exc}"
                ) from exc
            except httpx.RequestError as exc:
                raise ProviderError(f"WahaClient: request failed: {exc}") from exc

        response_text = response.text
        if _is_ban_response(response.status_code, response_text):
            logger.warning(
                "WAHA ban signal: status=%s body=%.200s", response.status_code, response_text
            )
            raise BanDetectedError(
                f"WahaClient: ban detected (HTTP {response.status_code}): {response_text[:200]}"
            )

        if response.status_code not in (200, 201):
            raise ProviderError(
                f"WahaClient: unexpected status {response.status_code}: {response_text[:200]}"
            )

        data = response.json()
        # WAHA returns {"id": "...", ...}
        message_id: str = data.get("id", "")
        if not message_id:
            raise ProviderError(f"WahaClient: response missing 'id' field: {data}")

        logger.debug("WahaClient: sent message_id=%s to=%s", message_id, to)
        return message_id

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: list | None = None,
    ) -> str:
        # WAHA does not natively support Meta Templates.
        # This method exists to satisfy the interface; the router never
        # calls it on the WAHA client.
        raise NotImplementedError("WahaClient does not support Meta template messages.")

    async def health_check(self, session_id: str = "default") -> bool:
        """
        GET /api/sessions/{session_id}

        Returns True only if the session status is "WORKING".
        """
        url = f"{self._base_url}/api/sessions/{session_id}"
        async with httpx.AsyncClient(headers=self._headers, timeout=5.0) as client:
            try:
                response = await client.get(url)
            except httpx.RequestError as exc:
                logger.warning("WahaClient health_check failed: %s", exc)
                return False

        if response.status_code != 200:
            return False

        data = response.json()
        status = data.get("status", "")
        is_working = status == "WORKING"
        logger.debug("WahaClient health_check: session=%s status=%s working=%s", session_id, status, is_working)
        return is_working
