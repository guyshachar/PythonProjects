"""
MessageRouter – orchestrates outbound message routing with automatic failover.

Decision tree for every outbound send request:

                      ┌─────────────────────────────┐
                      │   POST /v1/messages arrives  │
                      └──────────────┬──────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │  What is the state? │
                          └──────┬──────┬───────┘
                    NORMAL ◄─────┘      └─────► BANNED
                      │                              │
          ┌───────────▼────────────┐     ┌───────────▼──────────────────┐
          │  Send via WAHA         │     │  Has ban TTL expired?         │
          └─┬──────────────────┬──┘     └──┬─────────────────┬──────────┘
       OK  │             BanError│       NO │              YES │
            │                   │           │                  │
            ▼                   │           ▼                  ▼
        Return              ┌───▼───┐  Send via Meta    Probe WAHA
       response             │ Ban!  │  (failover)      health_check()
                            │ set   │                   ┌──────┴──────┐
                            │BANNED │                 FAIL          OK
                            └───┬───┘                  │              │
                                │               Stay BANNED     Set NORMAL
                                ▼               send via Meta   send via WAHA
                         Retry via Meta                         Return response
                         (failover_triggered=True)

Meta send logic:
  - If the customer has an active 24-hour conversation window (they messaged
    us recently), send a free-form text message.
  - Otherwise, send the pre-approved failover template.
  - After sending, mark the conversation window (Redis key with 24h TTL).

Conversation window key:
  meta:conv_window:{customer_number}   TTL: 86400 seconds
"""

import logging
from typing import Optional

from app.clients.base import BanDetectedError, IChannelClient, ProviderError
from app.clients.meta_client import MetaCloudClient
from app.clients.waha_client import WahaClient
from app.models.outbound import SendMessageRequest, SendMessageResponse
from app.models.unified import ChannelProvider
from app.services.redis_client import RedisClient
from app.services.state_manager import ChannelState, StateManager

logger = logging.getLogger(__name__)

_CONV_WINDOW_PREFIX = "meta:conv_window:"
_CONV_WINDOW_TTL = 86400  # 24 hours in seconds


class MessageRouter:
    """
    Stateless orchestrator – all mutable state lives in Redis.

    Injected via FastAPI's dependency system (one instance per app lifetime).
    """

    def __init__(
        self,
        waha: WahaClient,
        meta: MetaCloudClient,
        state_manager: StateManager,
        redis: RedisClient,
    ) -> None:
        self._waha = waha
        self._meta = meta
        self._state_manager = state_manager
        self._redis = redis

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def send(self, request: SendMessageRequest) -> SendMessageResponse:
        """
        Route a message to the appropriate channel with automatic failover.
        """
        state = await self._state_manager.get_state(request.session_id)

        if state == ChannelState.NORMAL:
            return await self._send_normal(request)
        else:
            return await self._send_banned(request, failover_triggered=False)

    # -----------------------------------------------------------------------
    # Private routing strategies
    # -----------------------------------------------------------------------

    async def _send_normal(self, request: SendMessageRequest) -> SendMessageResponse:
        """Try WAHA; on ban, flip state and transparently fall through to Meta."""
        try:
            message_id = await self._waha.send_text(
                to=request.to,
                body=request.body,
                session_id=request.session_id,
            )
            logger.info(
                "MessageRouter: sent via WAHA | to=%s message_id=%s", request.to, message_id
            )
            return SendMessageResponse(
                message_id=message_id,
                provider=ChannelProvider.WAHA,
                channel_state=ChannelState.NORMAL.value,
                failover_triggered=False,
            )

        except BanDetectedError as exc:
            logger.error(
                "MessageRouter: ban detected on session '%s': %s – triggering failover.",
                request.session_id,
                exc,
            )
            await self._state_manager.set_banned(request.session_id)
            # Transparent failover: CRM is informed via failover_triggered=True.
            return await self._send_banned(request, failover_triggered=True)

        except ProviderError as exc:
            # Non-ban WAHA failure: surface to the caller, do NOT failover.
            logger.error("MessageRouter: WAHA ProviderError: %s", exc)
            raise

    async def _send_banned(
        self, request: SendMessageRequest, failover_triggered: bool
    ) -> SendMessageResponse:
        """
        Route via Meta.  If ban TTL has expired, probe WAHA first; if it's
        healthy again, transition back to NORMAL and deliver via WAHA instead.
        """
        # ── Recovery probe ──────────────────────────────────────────────────
        if not failover_triggered and await self._state_manager.is_ban_expired(request.session_id):
            logger.info(
                "MessageRouter: ban TTL expired for session '%s'; probing WAHA.", request.session_id
            )
            waha_alive = await self._waha.health_check(request.session_id)

            if waha_alive:
                await self._state_manager.set_normal(request.session_id)
                logger.info("MessageRouter: WAHA recovered – routing this message via WAHA.")
                return await self._send_normal(request)
            else:
                # Ban still active – reset the TTL so we don't probe every request.
                await self._state_manager.set_banned(request.session_id)
                logger.info("MessageRouter: WAHA still unreachable; staying on Meta.")

        # ── Deliver via Meta ─────────────────────────────────────────────────
        message_id = await self._route_via_meta(request)

        logger.info(
            "MessageRouter: sent via Meta Cloud | to=%s message_id=%s failover=%s",
            request.to,
            message_id,
            failover_triggered,
        )
        return SendMessageResponse(
            message_id=message_id,
            provider=ChannelProvider.META_CLOUD,
            channel_state=ChannelState.BANNED.value,
            failover_triggered=failover_triggered,
        )

    async def _route_via_meta(self, request: SendMessageRequest) -> str:
        """
        Choose between free-form text and a template based on whether an active
        24-hour conversation window exists for this customer.
        """
        # Check conversation window (set when we last received an inbound from this customer).
        has_window = await self._has_conversation_window(request.to)

        if has_window:
            # Customer recently messaged us → we can reply freely.
            logger.debug("MessageRouter: Meta free-form send (active window) to=%s", request.to)
            return await self._meta.send_text(to=request.to, body=request.body)
        else:
            # No recent customer message → must use a pre-approved template.
            # Use the request-level template override if provided, else the default.
            template_name = request.template_name or None
            template_lang = request.template_language or None

            logger.debug(
                "MessageRouter: Meta template send (no window) to=%s template=%s",
                request.to,
                template_name or "(default)",
            )

            if template_name and template_lang:
                message_id = await self._meta.send_template(
                    to=request.to,
                    template_name=template_name,
                    language_code=template_lang,
                )
            else:
                message_id = await self._meta.send_failover_template(to=request.to)

            # Opening a conversation window: our template message starts a 24h window
            # on the Meta side, but we set the flag here so subsequent *inbound*
            # messages from the customer (tracked by the webhook ingress) keep it alive.
            return message_id

    # -----------------------------------------------------------------------
    # Conversation window helpers
    # -----------------------------------------------------------------------

    async def _has_conversation_window(self, customer_number: str) -> bool:
        """Return True if a 24-hour inbound conversation window is active."""
        key = f"{_CONV_WINDOW_PREFIX}{customer_number}"
        value = await self._redis._client.get(key)
        return value is not None

    async def mark_conversation_window(self, customer_number: str) -> None:
        """
        Called by the webhook ingress router whenever an inbound message is
        received.  Keeps the 24-hour window alive so outbound replies can use
        free-form text instead of templates.
        """
        key = f"{_CONV_WINDOW_PREFIX}{customer_number}"
        await self._redis._client.set(key, "1", ex=_CONV_WINDOW_TTL)
        logger.debug("MessageRouter: conversation window refreshed for %s", customer_number)
