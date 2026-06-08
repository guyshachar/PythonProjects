"""
Outbound message router – POST /v1/messages

The CRM sends a SendMessageRequest here; OnWays decides the channel,
handles failover transparently, and returns a SendMessageResponse.

Authentication:
  Requires the X-Api-Key header when GATEWAY_API_KEY is configured.

Errors surfaced to the CRM:
  • 401 Unauthorized  – missing or invalid API key.
  • 503 Service Unavailable – both channels failed to deliver.
  • 422 Unprocessable Entity – malformed request body (Pydantic).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.security import require_api_key
from app.models.outbound import SendMessageRequest, SendMessageResponse
from app.services.router_service import MessageRouter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/messages",
    tags=["messages"],
    dependencies=[Depends(require_api_key)],   # applied to ALL routes in this router
)


def get_router(request: Request) -> MessageRouter:
    return request.app.state.message_router


@router.post(
    "",
    summary="Send a WhatsApp message (with automatic failover)",
    response_model=SendMessageResponse,
    status_code=status.HTTP_200_OK,
)
async def send_message(
    payload: SendMessageRequest,
    message_router: MessageRouter = Depends(get_router),
) -> SendMessageResponse:
    """
    Deliver a WhatsApp message via the optimal channel.

    - If the primary channel (WAHA) is `NORMAL`, it is used.
    - If WAHA returns a ban signal, the state transitions to `BANNED`
      automatically and this same request is retried via Meta Cloud API.
      `failover_triggered: true` in the response tells the CRM.
    - While `BANNED`, all messages route through Meta.  Once the ban TTL
      expires and WAHA probes successfully, the state reverts to `NORMAL`.
    """
    try:
        return await message_router.send(payload)
    except Exception as exc:
        logger.error("All channels failed for to=%s: %s", payload.to, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"All channels failed to deliver message: {exc}",
        ) from exc
