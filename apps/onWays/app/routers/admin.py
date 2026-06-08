"""
Admin / ops endpoints  –  /v1/admin/…

All routes require the X-Api-Key header (same key as /v1/messages).

Routes
──────
GET  /v1/admin/state/{session_id}
  Returns the current routing state (normal/banned) and ban timestamps.

POST /v1/admin/state/{session_id}/reset
  Force-transitions the session back to NORMAL.
  Use after manually resolving a ban (e.g. WhatsApp support restored it).

POST /v1/admin/state/{session_id}/ban
  Force-transitions the session to BANNED.
  Use for planned maintenance windows or testing failover.

GET  /v1/admin/dead-letter?limit=N
  Returns the most recent N failed CRM forward events from the dead-letter
  queue.  Useful for manual replay or debugging.

GET  /v1/admin/health
  Detailed health check: Redis ping + current state for the default session.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.core.security import require_api_key
from app.services.state_manager import ChannelState, StateManager

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_api_key)],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class StateResponse(BaseModel):
    session_id: str
    state: str
    banned_at: str | None = None
    expires_at: str | None = None


class ActionResponse(BaseModel):
    session_id: str
    new_state: str
    message: str


class HealthResponse(BaseModel):
    status: str
    redis: str
    default_channel_state: str
    version: str = "0.4.0"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def get_state_manager(request: Request) -> StateManager:
    return request.app.state.state_manager


def get_crm_forwarder(request: Request):
    return request.app.state.crm_forwarder


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/state/{session_id}",
    response_model=StateResponse,
    summary="Get current routing state for a session",
)
async def get_state(
    session_id: str,
    state_manager: StateManager = Depends(get_state_manager),
) -> StateResponse:
    data = await state_manager.get_state_data(session_id)
    return StateResponse(
        session_id=session_id,
        state=data.get("state", ChannelState.NORMAL.value),
        banned_at=data.get("banned_at"),
        expires_at=data.get("expires_at"),
    )


@router.post(
    "/state/{session_id}/reset",
    response_model=ActionResponse,
    summary="Force session back to NORMAL (manual ban recovery)",
)
async def reset_state(
    session_id: str,
    state_manager: StateManager = Depends(get_state_manager),
) -> ActionResponse:
    await state_manager.set_normal(session_id)
    logger.info("Admin: session '%s' manually reset to NORMAL.", session_id)
    return ActionResponse(
        session_id=session_id,
        new_state=ChannelState.NORMAL.value,
        message=f"Session '{session_id}' has been reset to NORMAL. "
                "Next outbound message will route via WAHA.",
    )


@router.post(
    "/state/{session_id}/ban",
    response_model=ActionResponse,
    summary="Force session into BANNED (maintenance / testing)",
    status_code=status.HTTP_200_OK,
)
async def force_ban(
    session_id: str,
    state_manager: StateManager = Depends(get_state_manager),
) -> ActionResponse:
    await state_manager.set_banned(session_id)
    logger.info("Admin: session '%s' manually forced to BANNED.", session_id)
    return ActionResponse(
        session_id=session_id,
        new_state=ChannelState.BANNED.value,
        message=f"Session '{session_id}' has been forced to BANNED. "
                "Outbound messages will route via Meta until the ban TTL expires "
                "or you call /reset.",
    )


@router.get(
    "/dead-letter",
    summary="Inspect CRM forwarding failures",
)
async def get_dead_letter(
    limit: int = Query(default=20, ge=1, le=200),
    crm_forwarder=Depends(get_crm_forwarder),
) -> dict:
    entries = await crm_forwarder.get_dead_letter_entries(limit=limit)
    return {"count": len(entries), "entries": entries}


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Detailed health check with Redis and channel state",
)
async def detailed_health(
    request: Request,
    state_manager: StateManager = Depends(get_state_manager),
) -> HealthResponse:
    # Ping Redis.
    redis_status = "ok"
    try:
        await request.app.state.redis._client.ping()
    except Exception as exc:
        logger.error("Admin health: Redis ping failed: %s", exc)
        redis_status = f"error: {exc}"

    channel_state = await state_manager.get_state("default")

    return HealthResponse(
        status="ok" if redis_status == "ok" else "degraded",
        redis=redis_status,
        default_channel_state=channel_state.value,
    )
