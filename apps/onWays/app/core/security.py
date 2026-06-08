"""
Security helpers for the OnWays gateway.

Two concerns:

1. API Key guard  (POST /v1/messages)
   ─────────────────────────────────
   The CRM must present a shared secret in the `X-Api-Key` request header.
   Enforcement is skipped when GATEWAY_API_KEY is blank (dev mode).

2. Meta webhook verification
   ─────────────────────────
   a) GET  /v1/webhooks/meta  – hub subscription challenge
      Meta sends hub.verify_token; we compare it to META_WEBHOOK_VERIFY_TOKEN.

   b) POST /v1/webhooks/meta  – payload HMAC signature
      Meta signs every POST body with the app secret and sets
      X-Hub-Signature-256: sha256=<hex>.  We verify this before parsing.
      Enforcement is skipped when META_APP_SECRET is blank (dev mode).
"""

import hashlib
import hmac
import logging

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. API Key guard
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


def require_api_key(
    api_key: str | None = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    FastAPI dependency – inject into any endpoint that should be protected.

    If GATEWAY_API_KEY is not configured, the check is skipped (dev-friendly).
    In production, any request without the correct key gets a 401.
    """
    if not settings.gateway_api_key:
        # Not configured → enforcement disabled.
        return

    if not api_key or api_key != settings.gateway_api_key:
        logger.warning("Rejected request: invalid or missing X-Api-Key header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


# ---------------------------------------------------------------------------
# 2. Meta HMAC verification
# ---------------------------------------------------------------------------

def verify_meta_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """
    Pure function – returns True if the signature is valid.

    signature_header is the value of X-Hub-Signature-256, e.g.:
      "sha256=abcdef1234..."
    """
    if not app_secret:
        # Secret not configured → skip verification (dev mode).
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    received_hex = signature_header[len("sha256="):]
    expected_hex = hmac.new(
        app_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected_hex, received_hex)


def require_meta_signature(request: Request, settings: Settings = Depends(get_settings)):
    """
    FastAPI dependency – validates X-Hub-Signature-256 on Meta webhook POSTs.

    Must be used AFTER the raw body has been buffered (call request.body()
    before this or use it alongside the raw-body approach in the endpoint).

    NOTE: this dependency is synchronous; the actual check is done in the
    endpoint after reading the raw body.  This function is provided as a
    convenience carrier of settings only.  The endpoint calls
    verify_meta_signature() directly.
    """
    return settings
