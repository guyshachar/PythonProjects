"""
URL validation using scoutCut's classification logic.

Imports _looks_like_url() and _PLATFORM_MARKERS from scoutCut.py so the
same format rules and platform detection are shared between the CLI tool
and the web validation endpoint.  The actual network check is a lightweight
HTTP HEAD (falling back to a byte-range GET) — the heavy Playwright scrapers
are NOT invoked here.
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

# ── Reuse scoutCut's helpers ───────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scoutCut import _PLATFORM_MARKERS, _looks_like_url  # noqa: E402

_PLATFORM_LABELS: dict[str, str] = {
    "pixellot.link": "Pixellot",
    "live.veo.co":   "Veo",
}

_HEADERS = {"User-Agent": "ScoutCut-Validator/1.0"}


async def validate_url(url: str) -> dict:
    """
    Validate a single URL.  Returns a dict with:
        url, valid (bool), status ("valid"|"warning"|"invalid"),
        message (human-readable), platform (str|None)
    """
    url = url.strip()

    # ── Step 1: format check (scoutCut's own rule) ────────────────────────────
    if not _looks_like_url(url):
        return _result(url, False, "invalid", "URL must start with http:// or https://")

    if not urlparse(url).netloc:
        return _result(url, False, "invalid", "Invalid URL — missing host")

    # ── Step 2: platform classification (scoutCut's _PLATFORM_MARKERS) ────────
    platform = next(
        (_PLATFORM_LABELS.get(m, m) for m in _PLATFORM_MARKERS if m in url),
        None,
    )

    # ── Step 3: lightweight HTTP reachability check ───────────────────────────
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            verify=False,       # CDN certs sometimes mismatch
        ) as client:
            try:
                resp = await client.head(url, headers=_HEADERS)
            except Exception:
                # Some servers reject HEAD — fall back to a 1-byte GET
                resp = await client.get(
                    url,
                    headers={**_HEADERS, "Range": "bytes=0-0"},
                )

            sc = resp.status_code

            if sc < 400:
                label = f"{platform} — " if platform else ""
                return _result(url, True, "valid", f"{label}Reachable ({sc})", platform)

            if sc in (401, 403):
                # Auth-gated is normal for Pixellot / Veo; scoutCut handles login
                label = f"{platform}: " if platform else ""
                return _result(
                    url, True, "warning",
                    f"{label}Requires authentication ({sc}) — ScoutCut will handle login",
                    platform,
                )

            if sc == 404:
                return _result(url, False, "invalid", "Not found (404)", platform)

            return _result(url, False, "invalid", f"HTTP {sc}", platform)

    except httpx.TimeoutException:
        return _result(url, False, "invalid", "Request timed out", platform)
    except Exception as exc:
        return _result(url, False, "invalid", f"Unreachable: {str(exc)[:80]}", platform)


def _result(
    url: str,
    valid: bool,
    status: str,
    message: str,
    platform: str | None = None,
) -> dict:
    return {"url": url, "valid": valid, "status": status, "message": message, "platform": platform}
