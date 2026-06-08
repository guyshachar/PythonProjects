"""
Centralised configuration for the OnWays gateway.

All environment variables are declared here with types and defaults.
The application reads this once at startup; every service receives the
Settings object rather than calling os.environ.get() directly.

pydantic-settings reads from:
  1. Actual environment variables (highest priority)
  2. A .env file in the working directory (if present)

Required-at-runtime fields have no default and will raise a
ValidationError on startup if they are missing.  Fields that are only
needed for a specific provider (e.g. META_APP_SECRET) default to "" and
are checked in the security layer when that provider is active.
"""

import os
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # ignore unknown env vars silently
    )

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── WAHA (primary channel) ───────────────────────────────────────────────
    waha_base_url: str = "http://localhost:3000"
    waha_api_key: str = ""

    # ── Meta Cloud API (shadow channel) ─────────────────────────────────────
    meta_phone_number_id: str = ""
    meta_access_token: str = ""
    meta_api_version: str = "v19.0"
    meta_template_name: str = "failover_greeting"
    meta_template_language: str = "en_US"

    # Secret used to verify the hub.verify_token on the Meta webhook GET challenge.
    meta_webhook_verify_token: str = ""
    # App secret used to verify X-Hub-Signature-256 on Meta webhook POSTs.
    # Leave blank in dev to disable HMAC enforcement.
    meta_app_secret: str = ""

    # ── Gateway security ─────────────────────────────────────────────────────
    # API key the CRM must send in the X-Api-Key header when calling
    # POST /v1/messages.  Leave blank in dev to disable enforcement.
    gateway_api_key: str = ""

    # ── CRM forwarding ───────────────────────────────────────────────────────
    # URL to which OnWays POSTs every normalised UnifiedMessage / ReadReceipt.
    # Leave blank to disable forwarding (useful in dev/testing).
    crm_webhook_url: str = ""
    # Shared secret sent as X-Onways-Signature header on CRM forward requests.
    crm_webhook_secret: str = ""
    # Number of HTTP attempts before a failed forward goes to dead-letter.
    crm_max_retries: int = 3

    # ── Failover / state ─────────────────────────────────────────────────────
    ban_recovery_seconds: int = 86400   # 24 hours

    # ── App ──────────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    allowed_origins: str = "*"

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}, got '{v}'.")
        return upper

    @model_validator(mode="after")
    def _warn_missing_production_fields(self) -> "Settings":
        """
        Log warnings for fields that will cause runtime failures if the
        corresponding provider is actually used.  We warn rather than raising
        so that the app can still start in dev with only WAHA configured.
        """
        import logging
        log = logging.getLogger(__name__)

        if not self.meta_phone_number_id or not self.meta_access_token:
            log.warning(
                "Settings: META_PHONE_NUMBER_ID / META_ACCESS_TOKEN not set. "
                "Meta Cloud API (shadow channel) will fail if triggered."
            )
        if not self.meta_app_secret:
            log.warning(
                "Settings: META_APP_SECRET not set – "
                "HMAC signature verification on Meta webhooks is DISABLED."
            )
        if not self.gateway_api_key:
            log.warning(
                "Settings: GATEWAY_API_KEY not set – "
                "POST /v1/messages is unauthenticated. Do not use in production."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    lru_cache ensures the .env file is only read once per process.
    In tests, call get_settings.cache_clear() before overriding env vars.
    """
    return Settings()
