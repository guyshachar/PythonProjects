#!/usr/bin/env python3
"""
veo_scraper.py

Opens a live.veo.co match URL in Chromium, intercepts network traffic,
and extracts the underlying video stream URL (HLS .m3u8 or direct .mp4).

Authentication:
  On first run the browser window is VISIBLE — log in with your Veo account.
  Your session is saved to the veo_profile/ directory.
  Subsequent runs run headless using that saved session.

Usage:
    python3 veo_scraper.py "https://live.veo.co/matches/UUID@TIMESTAMP"
    python3 veo_scraper.py --reset  # clear saved session and re-login
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from playwright.sync_api import sync_playwright

PROFILE_DIR = Path(__file__).parent / "veo_profile"

# URL patterns that indicate a video stream
_STREAM_PATTERNS = [
    re.compile(r"\.m3u8(\?|$)"),
    re.compile(r"\.mpd(\?|$)"),
    re.compile(r"stream\.mux\.com"),
    re.compile(r"c\.veocdn\.com/.+\.(m3u8|mp4|mpd)"),
]

# API domains whose JSON responses may contain stream URLs
_API_DOMAINS = ("api.veo.co", "live.veo.co", "app.veo.co", "veocdn.com", "mux.com")


def _is_stream_url(url: str) -> bool:
    return any(p.search(url) for p in _STREAM_PATTERNS)


def _extract_from_json(text: str) -> list[str]:
    """Pull any video stream URLs out of a JSON blob."""
    found = []
    for m in re.findall(r'https://[^\s"\'\\]+\.m3u8[^\s"\'\\]*', text):
        found.append(m)
    for m in re.findall(r'https://[^\s"\'\\]+\.mpd[^\s"\'\\]*', text):
        found.append(m)
    for m in re.findall(r'https://stream\.mux\.com/[^\s"\'\\]+', text):
        found.append(m)
    # Veo CDN mp4 URLs (direct video files)
    for m in re.findall(r'https://c\.veocdn\.com/[^\s"\'\\]+\.mp4', text):
        found.append(m)
    return found


def extract_stream_url(match_url: str, timeout: int = 60_000) -> str | None:
    found: list[str] = []
    headless = PROFILE_DIR.exists()

    def _on_request(req):
        url = req.url
        if _is_stream_url(url) and url not in found:
            print(f"  [stream-req]  {url}")
            found.append(url)

    def _on_response(resp):
        url = resp.url
        if _is_stream_url(url) and url not in found:
            print(f"  [stream-resp] {url}")
            found.append(url)
            return
        if any(d in url for d in _API_DOMAINS) and resp.status == 200:
            try:
                ct = resp.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct or "text" in ct:
                    text = resp.text()
                    hits = _extract_from_json(text)
                    for h in hits:
                        if h not in found:
                            print(f"  [api]         {h}")
                            found.append(h)
            except Exception:
                pass

    with sync_playwright() as p:
        if headless:
            print(f"Using saved session from {PROFILE_DIR}/")
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=True,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
        else:
            print(
                "No saved session found — opening browser for login.\n"
                "  1. Log in to your Veo account in the browser window.\n"
                "  2. Once logged in, navigate to the match URL manually if needed.\n"
                "  3. Wait for the video player to load.\n"
                "  4. The script will detect the stream and close automatically.\n"
            )
            ctx = p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )

        page = ctx.new_page()
        page.on("request", _on_request)
        page.on("response", _on_response)

        try:
            print(f"Loading: {match_url}")
            page.goto(match_url, wait_until="domcontentloaded", timeout=timeout)

            elapsed = 0
            interval = 1_000
            while not found and elapsed < timeout:
                page.wait_for_timeout(interval)
                elapsed += interval
                if elapsed % 5_000 == 0 and not headless:
                    print(f"  Waiting for stream... ({elapsed // 1000}s)")

        except Exception as e:
            print(f"  [error] {e}")
        finally:
            ctx.close()

    return _best_url(found)


def _best_url(urls: list[str]) -> str | None:
    if not urls:
        return None
    # Prefer m3u8 over mp4 over mpd
    for u in urls:
        if ".m3u8" in u:
            return u
    for u in urls:
        if ".mp4" in u:
            return u
    return urls[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract video stream URL from a live.veo.co match link."
    )
    parser.add_argument("url", nargs="?", help="live.veo.co match URL")
    parser.add_argument(
        "--timeout", type=int, default=60, metavar="SECS",
        help="Max seconds to wait for stream URL (default: 60)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Delete saved session and force re-login",
    )
    args = parser.parse_args()

    if args.reset:
        if PROFILE_DIR.exists():
            shutil.rmtree(PROFILE_DIR)
            print(f"Deleted saved session at {PROFILE_DIR}/")
        else:
            print("No saved session to delete.")
        if not args.url:
            sys.exit(0)

    if not args.url:
        parser.error("url is required unless --reset is used alone")

    result = extract_stream_url(args.url, timeout=args.timeout * 1_000)

    if result:
        print(f"\n[SUCCESS] Stream URL:\n  {result}")
        print("\nUse this URL directly in yoav_input.csv.")
    else:
        print("\n[FAILED] No stream URL found.")
        if not PROFILE_DIR.exists():
            print("Tip: The browser may not have been logged in.")
            print("     Run again — it will open a browser window for login.")
        else:
            print("Tip: Try --reset to clear the saved session and re-login.")
        sys.exit(1)
