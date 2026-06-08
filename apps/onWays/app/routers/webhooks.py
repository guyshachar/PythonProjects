"""
Webhook ingress router – the front door of the OnWays gateway.

Routes
──────
GET  /v1/webhooks/meta            – Meta hub subscription challenge
POST /v1/webhooks/{provider}      – Ingest raw webhook payloads

POST flow
─────────
  1. Read raw body bytes (needed for Meta HMAC verification).
  2. If provider == "meta": verify X-Hub-Signature-256.
  3. Deserialise JSON.
  4. Select the correct parser (Strategy Pattern).
  5. Normalise the payload.
  6. Idempotency check via Redis SET NX.
  7. Refresh the Meta conversation window for inbound messages.
  8. Forward the unified event to the CRM (fire-and-forward).
  9. Return the unified event.
"""

import json
import logging
from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import Settings, get_settings
from app.core.security import verify_meta_signature
from app.models.unified import MessageDirection, UnifiedMessage, UnifiedReadReceipt
from app.parsers.base import IWebhookParser, ParsedEvent
from app.parsers.meta import MetaCloudWebhookParser
from app.parsers.waha import WahaWebhookParser
from app.services.crm_forwarder import CrmForwarder
from app.services.redis_client import RedisClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])

# ---------------------------------------------------------------------------
# Registered parsers (order matters: first match wins).
# ---------------------------------------------------------------------------
_PARSERS: list[IWebhookParser] = [
    WahaWebhookParser(),
    MetaCloudWebhookParser(),
]

_PARSER_MAP: dict[str, IWebhookParser] = {
    "waha": WahaWebhookParser(),
    "meta": MetaCloudWebhookParser(),
}


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_redis(request: Request) -> RedisClient:
    return request.app.state.redis


def get_crm_forwarder(request: Request) -> CrmForwarder:
    return request.app.state.crm_forwarder


def get_message_router(request: Request):
    return getattr(request.app.state, "message_router", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_parser(provider_hint: str, payload: dict) -> IWebhookParser:
    hinted = _PARSER_MAP.get(provider_hint.lower())
    if hinted and hinted.can_parse(payload):
        return hinted
    for parser in _PARSERS:
        if parser.can_parse(payload):
            return parser
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"No parser found for provider hint '{provider_hint}'. "
               "Payload signature not recognised.",
    )


# ---------------------------------------------------------------------------
# GET /v1/webhooks/meta  – Meta hub subscription challenge
# ---------------------------------------------------------------------------

@router.get(
    "/meta",
    summary="Meta webhook hub verification",
    include_in_schema=True,
    tags=["webhooks"],
)
async def meta_webhook_challenge(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> PlainTextResponse:
    """
    Called by Meta when you save the webhook URL in the app dashboard.
    Responds with the challenge value if the verify token matches.
    """
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and hub_verify_token == settings.meta_webhook_verify_token
    ):
        logger.info("Meta webhook challenge verified successfully.")
        return PlainTextResponse(content=hub_challenge or "")

    logger.warning(
        "Meta webhook challenge FAILED: mode=%s token_match=%s",
        hub_mode,
        hub_verify_token == settings.meta_webhook_verify_token,
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Webhook verification token mismatch.",
    )


# ---------------------------------------------------------------------------
# POST /v1/webhooks/{provider}  – Ingest raw webhook payloads
# ---------------------------------------------------------------------------

@router.post(
    "/{provider}",
    summary="Ingest a raw webhook from WAHA or Meta Cloud API",
    response_model=Union[UnifiedMessage, UnifiedReadReceipt],
    status_code=status.HTTP_200_OK,
)
async def ingest_webhook(
    provider: str,
    request: Request,
    redis: RedisClient = Depends(get_redis),
    crm_forwarder: CrmForwarder = Depends(get_crm_forwarder),
    message_router=Depends(get_message_router),
    settings: Settings = Depends(get_settings),
) -> Any:
    """
    Main ingress endpoint.

    1. Read raw body bytes.
    2. Verify Meta HMAC signature (if provider == 'meta' and secret is configured).
    3. Deserialise JSON.
    4. Select parser via Strategy Pattern.
    5. Normalise payload.
    6. Idempotency check (Redis SET NX).
    7. Refresh Meta 24-hour conversation window for inbound messages.
    8. Forward normalised event to CRM (fire-and-forward).
    9. Return normalised event.
    """

    # ── Step 1: Read raw body ────────────────────────────────────────────────
    # We read bytes (not request.json()) so we can compute the HMAC before
    # any parsing happens.
    body_bytes: bytes = await request.body()

    # ── Step 2: Meta HMAC verification ──────────────────────────────────────
    if provider.lower() == "meta":
        sig_header: str | None = request.headers.get("X-Hub-Signature-256")
        if not verify_meta_signature(body_bytes, sig_header, settings.meta_app_secret):
            logger.warning(
                "Meta webhook HMAC verification failed (sig_header=%s)", sig_header
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature.",
            )

    # ── Step 3: Deserialise JSON ─────────────────────────────────────────────
    try:
        raw_payload: dict = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        logger.warning("Malformed JSON from provider '%s': %s", provider, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not valid JSON.",
        ) from exc

    if not isinstance(raw_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must be a JSON object.",
        )

    # ── Step 4: Select parser ────────────────────────────────────────────────
    parser = _select_parser(provider, raw_payload)

    # ── Step 5: Normalise ────────────────────────────────────────────────────
    try:
        event: ParsedEvent = parser.parse(raw_payload)
    except NotImplementedError as exc:
        logger.info("Provider '%s' sent an unsupported event type: %s", provider, exc)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": str(exc), "skipped": True},
        )
    except ValueError as exc:
        logger.error("Parser failed for '%s': %s | payload=%s", provider, exc, raw_payload)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Payload structure error: {exc}",
        ) from exc

    # ── Step 6: Idempotency check ────────────────────────────────────────────
    message_id = event.message_id
    if await redis.is_duplicate(message_id):
        logger.debug("Duplicate webhook ignored: message_id=%s", message_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"detail": "Duplicate event; already processed.", "message_id": message_id},
        )

    # ── Step 7: Refresh Meta conversation window ─────────────────────────────
    if (
        message_router is not None
        and isinstance(event, UnifiedMessage)
        and event.direction == MessageDirection.INBOUND
    ):
        await message_router.mark_conversation_window(event.from_number)

    # ── Step 8: Forward to CRM ───────────────────────────────────────────────
    await crm_forwarder.forward(event)

    # ── Step 9: Return normalised event ─────────────────────────────────────
    logger.info(
        "Processed %s event: message_id=%s provider=%s",
        event.event_type,
        message_id,
        provider,
    )
    return event
