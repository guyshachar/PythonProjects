#!/usr/bin/env python3
"""
pixellot_scraper.py

Opens a Pixellot share URL in a headless Chromium browser, intercepts
network traffic, and extracts the underlying HLS (.m3u8) stream URL.

The m3u8 URL is discovered via two signals (whichever fires first):
  1. The Pixellot API response for /api/v1/events/<id>
  2. The mediaResource= parameter in analytics requests (youboranqs01.com)

Usage:
    python3 pixellot_scraper.py "https://you.pixellot.link/nwbJozByx3b"
"""

import argparse
import json
import re
from urllib.parse import urlparse, parse_qs, unquote
from playwright.sync_api import sync_playwright


def extract_stream_url(match_url: str, timeout: int = 30_000) -> str | None:
    found: list[str] = []

    def _check_url(url: str) -> None:
        # Signal 1: mediaResource= param in analytics pings
        if "youboranqs01.com" in url or "youborafds01.com" in url:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            media = params.get("mediaResource", [])
            for m in media:
                m = unquote(m)
                if ".m3u8" in m and m not in found:
                    print(f"  [analytics] {m}")
                    found.append(m)

        # Signal 2: direct m3u8 request (in case the browser supports HLS)
        if re.search(r"\.m3u8(\?|$)", url) and url not in found:
            print(f"  [request]   {url}")
            found.append(url)

    def _check_response(response) -> None:
        # Signal 3: Pixellot API event JSON contains the video URL
        if "/api/v1/events/" in response.url and response.status == 200:
            try:
                data = response.json()
                # Look for any field containing .m3u8
                text = json.dumps(data)
                for m in re.findall(r'https://[^\s"\']+\.m3u8', text):
                    if m not in found:
                        print(f"  [api]       {m}")
                        found.append(m)
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()
        page.on("request", lambda r: _check_url(r.url))
        page.on("response", _check_response)

        try:
            print(f"Loading: {match_url}")
            page.goto(match_url, wait_until="domcontentloaded", timeout=timeout)

            # Wait for stream URL — poll every 500ms up to timeout
            elapsed = 0
            interval = 500
            while not found and elapsed < timeout:
                page.wait_for_timeout(interval)
                elapsed += interval

        except Exception as e:
            print(f"  [error] {e}")
        finally:
            browser.close()

    # Prefer master/index playlists; fall back to any m3u8 found
    for url in found:
        if re.search(r"(master|index|hd_)\w*\.m3u8", url):
            return url
    return found[0] if found else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract HLS stream URL from a Pixellot share link."
    )
    parser.add_argument("url", help="Public Pixellot match URL")
    parser.add_argument(
        "--timeout", type=int, default=30, metavar="SECS",
        help="Max seconds to wait for stream URL (default: 30)",
    )
    args = parser.parse_args()

    result = extract_stream_url(args.url, timeout=args.timeout * 1000)

    if result:
        print(f"\n[SUCCESS] Stream URL:\n  {result}")
        print("\nUse this in yoav_input.csv instead of the share link.")
    else:
        print("\n[FAILED] No stream URL found.")
