"""
OnWays API Gateway – application entry point.

Service dependency graph
────────────────────────
  Settings (validated at startup)
  RedisClient
    ├── StateManager
    └── MessageRouter
          ├── WahaClient
          ├── MetaCloudClient
          ├── StateManager
          └── RedisClient
  CrmForwarder (uses RedisClient for dead-letter)
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.meta_client import MetaCloudClient
from app.clients.waha_client import WahaClient
from app.core.config import get_settings
from app.middleware.correlation import CorrelationIdMiddleware, RequestIdFilter
from app.routers import admin, messages, webhooks
from app.routers.monitor_ui import router as monitor_router
from app.services.crm_forwarder import CrmForwarder
from app.services.redis_client import RedisClient
from app.services.router_service import MessageRouter
from app.services.state_manager import StateManager


def create_app() -> FastAPI:
    settings = get_settings()

    # ── Logging ──────────────────────────────────────────────────────────────
    # Include request_id in every log line (populated by CorrelationIdMiddleware).
    log_format = (
        "%(asctime)s | %(levelname)-8s | [%(request_id)s] | %(name)s | %(message)s"
    )
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(logging.Formatter(log_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    # Replace any existing handlers so we don't double-print.
    root_logger.handlers = [handler]

    logger = logging.getLogger(__name__)

    # ── App ──────────────────────────────────────────────────────────────────
    app = FastAPI(
        title="OnWays WhatsApp Gateway",
        description=(
            "Hybrid WhatsApp API Gateway – normalises webhooks from WAHA and "
            "Meta Cloud API into a unified schema, and routes outbound messages "
            "with automatic failover to the Meta shadow channel."
        ),
        version="0.4.0",
    )

    # Middleware (outermost registered = innermost executed).
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins.split(","),
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    # ── Service lifecycle ────────────────────────────────────────────────────

    @app.on_event("startup")
    async def startup() -> None:
        redis = RedisClient(url=settings.redis_url)
        app.state.redis = redis

        state_manager = StateManager(redis=redis, ban_ttl_seconds=settings.ban_recovery_seconds)
        app.state.state_manager = state_manager

        waha_client = WahaClient(base_url=settings.waha_base_url, api_key=settings.waha_api_key)
        meta_client = MetaCloudClient(
            phone_number_id=settings.meta_phone_number_id,
            access_token=settings.meta_access_token,
            api_version=settings.meta_api_version,
            default_template_name=settings.meta_template_name,
            default_template_language=settings.meta_template_language,
        )

        app.state.message_router = MessageRouter(
            waha=waha_client,
            meta=meta_client,
            state_manager=state_manager,
            redis=redis,
        )

        app.state.crm_forwarder = CrmForwarder(
            crm_webhook_url=settings.crm_webhook_url,
            crm_webhook_secret=settings.crm_webhook_secret,
            max_retries=settings.crm_max_retries,
            redis_client=redis,
        )

        logger.info(
            "OnWays gateway v0.4.0 started. CRM forwarding: %s",
            f"enabled → {settings.crm_webhook_url} (max_retries={settings.crm_max_retries})"
            if settings.crm_webhook_url else "disabled",
        )

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await app.state.redis.close()
        logging.getLogger(__name__).info("Redis client closed.")

    # ── Routers ──────────────────────────────────────────────────────────────
    app.include_router(webhooks.router)
    app.include_router(messages.router)
    app.include_router(admin.router)
    app.include_router(monitor_router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "version": "0.4.0"}

    return app


app = create_app()
