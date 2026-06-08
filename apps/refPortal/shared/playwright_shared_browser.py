"""
Process-wide Playwright Chromium for gateway / long-lived workers.

One Playwright driver + one Browser per process; callers create BrowserContexts
per unit of work and close contexts when done. Launch options (headless, proxy)
must match for reuse; a change forces a browser relaunch under the lock.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Tuple

from playwright.async_api import Browser, Playwright

from shared.orgRelated.orgServiceBase import OrgServiceBase

_log = logging.getLogger(__name__)

_lock = asyncio.Lock()
_pw: Optional[Playwright] = None
_browser: Optional[Browser] = None
_headless: Optional[bool] = None
_use_proxy: Optional[bool] = None
# >0 while RefereeProcessService runs a batch against the process-wide browser (see enter/leave below).
_shared_referee_batch_depth = 0


def enter_shared_referee_batch() -> None:
    global _shared_referee_batch_depth
    _shared_referee_batch_depth += 1


def leave_shared_referee_batch() -> None:
    global _shared_referee_batch_depth
    _shared_referee_batch_depth = max(0, _shared_referee_batch_depth - 1)


def in_shared_referee_batch() -> bool:
    return _shared_referee_batch_depth > 0


async def _close_browser_unlocked() -> None:
    global _browser
    if _browser is not None:
        try:
            await _browser.close()
        except Exception as ex:
            _log.debug('shared browser.close: %s', ex)
        _browser = None


async def get_shared_browser(*, headless: bool, useProxy: bool = False) -> Tuple[Playwright, Browser]:
    """Return the process singleton Playwright + Browser, launching if needed."""
    global _pw, _browser, _headless, _use_proxy
    async with _lock:
        need_launch = (
            _browser is None
            or not _browser.is_connected()
            or _headless != headless
            or _use_proxy != useProxy
        )
        if need_launch and _browser is not None:
            await _close_browser_unlocked()
        if _pw is None:
            _pw = await OrgServiceBase.async_playwright_start()
        if _browser is None or not _browser.is_connected():
            _browser = await OrgServiceBase.launchBrowser(
                _pw, headless=headless, useProxy=useProxy
            )
            _headless = headless
            _use_proxy = useProxy
        return _pw, _browser


async def shutdown() -> None:
    """Close the shared browser and stop the Playwright driver."""
    global _pw, _browser, _headless, _use_proxy
    async with _lock:
        await _close_browser_unlocked()
        if _pw is not None:
            await OrgServiceBase.async_playwright_stop_safe(_pw)
            _pw = None
        _headless = None
        _use_proxy = None
