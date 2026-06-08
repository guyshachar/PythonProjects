"""
MetaCloudClient – outbound Strategy for the Meta (WhatsApp Cloud) API.

Used as the shadow channel when the primary WAHA channel is banned.

Meta Cloud API send endpoint:
  POST https://graph.facebook.com/{version}/{phone_number_id}/messages

Two delivery modes:
  1. Template message – required when the business opens a new conversation
     (no inbound message from the customer in the last 24 hours).
     Uses a pre-approved message template stored in Meta's template library.

  2. Free-form text message – allowed within the 24-hour customer service
     window (a customer sent a message to the business within the last 24h).

This client exposes both.  The RouterService decides which to use based on
the conversation window tracked in Redis.

References:
  https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
"""

import logging
import os
from typing import Any

import httpx

from app.clients.base import IChannelClient, ProviderError

logger = logging.getLogger(__name__)

_META_GRAPH_BASE = "https://graph.facebook.com"


class MetaCloudClient(IChannelClient):
    """
    Sends WhatsApp messages via the Meta (Facebook) Cloud API.

    Configuration (via environment variables):
      META_PHONE_NUMBER_ID  – the Cloud API phone number ID (not the display number)
      META_ACCESS_TOKEN     – a permanent System User token with whatsapp_business_messaging
      META_API_VERSION      – Graph API version, e.g. "v19.0" (default)
      META_TEMPLATE_NAME    – default pre-approved template name for failover greetings
      META_TEMPLATE_LANGUAGE – BCP-47 code for the default template, e.g. "en_US"
    """

    def __init__(
        self,
        phone_number_id: str | None = None,
        access_token: str | None = None,
        api_version: str | None = None,
        default_template_name: str | None = None,
        default_template_language: str | None = None,
    ) -> None:
        self._phone_number_id = phone_number_id or os.environ.get("META_PHONE_NUMBER_ID", "")
        self._access_token = access_token or os.environ.get("META_ACCESS_TOKEN", "")
        self._api_version = api_version or os.environ.get("META_API_VERSION", "v19.0")
        self._default_template_name = (
            default_template_name or os.environ.get("META_TEMPLATE_NAME", "failover_greeting")
        )
        self._default_template_language = (
            default_template_language or os.environ.get("META_TEMPLATE_LANGUAGE", "en_US")
        )

        if not self._phone_number_id or not self._access_token:
            logger.warning(
                "MetaCloudClient: META_PHONE_NUMBER_ID or META_ACCESS_TOKEN not configured. "
                "Outbound messages will fail."
            )

    # -----------------------------------------------------------------------
    # Private
    # -----------------------------------------------------------------------

    @property
    def _endpoint(self) -> str:
        return f"{_META_GRAPH_BASE}/{self._api_version}/{self._phone_number_id}/messages"

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict[str, Any]) -> str:
        """
        Send a POST to the Graph API and return the wamid (message ID).

        Raises ProviderError on any non-200 response.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    self._endpoint, json=payload, headers=self._auth_headers
                )
            except httpx.RequestError as exc:
                raise ProviderError(f"MetaCloudClient: request failed: {exc}") from exc

        response_text = response.text

        if response.status_code not in (200, 201):
            raise ProviderError(
                f"MetaCloudClient: unexpected status {response.status_code}: {response_text[:300]}"
            )

        data = response.json()
        # Graph API returns: {"messages": [{"id": "wamid.xxx"}], ...}
        try:
            message_id: str = data["messages"][0]["id"]
        except (KeyError, IndexError) as exc:
            raise ProviderError(
                f"MetaCloudClient: unexpected response shape: {data}"
            ) from exc

        logger.debug("MetaCloudClient: sent message_id=%s", message_id)
        return message_id

    # -----------------------------------------------------------------------
    # IChannelClient interface
    # -----------------------------------------------------------------------

    async def send_text(self, to: str, body: str, session_id: str = "default") -> str:
        """
        Send a free-form text message.

        Only valid within a 24-hour customer service window (a customer must
        have messaged the business first). Use send_template() for cold outreach.
        """
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        return await self._post(payload)

    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: list | None = None,
    ) -> str:
        """
        Send a pre-approved Meta template message.

        `components` is the list of header/body/button component objects as
        defined by the Graph API.  Pass None for templates with no parameters.

        This is the ONLY valid send method when no 24-hour service window is open.
        """
        template_payload: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language_code},
        }
        if components:
            template_payload["components"] = components

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "template",
            "template": template_payload,
        }
        return await self._post(payload)

    async def health_check(self, session_id: str = "default") -> bool:
        """
        Probe the Meta Cloud API by fetching the phone number object.

        GET /{version}/{phone_number_id}?fields=status
        Returns True only when the number is in CONNECTED status.
        """
        url = f"{_META_GRAPH_BASE}/{self._api_version}/{self._phone_number_id}"
        params = {"fields": "status", "access_token": self._access_token}

        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(url, params=params)
            except httpx.RequestError as exc:
                logger.warning("MetaCloudClient health_check failed: %s", exc)
                return False

        if response.status_code != 200:
            return False

        data = response.json()
        status = data.get("status", "")
        is_connected = status == "CONNECTED"
        logger.debug("MetaCloudClient health_check: status=%s connected=%s", status, is_connected)
        return is_connected

    # -----------------------------------------------------------------------
    # Convenience: send the default failover template
    # -----------------------------------------------------------------------

    async def send_failover_template(self, to: str) -> str:
        """
        Send the configured default failover template.

        Called by RouterService on the FIRST message delivered via Meta after
        a ban event, when no active 24-hour service window exists for this customer.
        """
        return await self.send_template(
            to=to,
            template_name=self._default_template_name,
            language_code=self._default_template_language,
        )
