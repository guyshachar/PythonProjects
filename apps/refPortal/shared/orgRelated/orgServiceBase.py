from datetime import datetime, timedelta
from urllib.parse import urlparse
import os
import sys
import time
from pathlib import Path
import asyncio
import re
import uuid
import logging
import requests
from contextlib import asynccontextmanager
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING
from playwright.async_api import async_playwright, BrowserContext, Page
from playwright_stealth import Stealth
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.handleUsers import HandleUsers
from shared.logger import Logger
from shared.db import CacheService
from shared.orgRelated.multiTenantSupport import MultiTenantSupport
from shared.configManager import ConfigManager

if TYPE_CHECKING:
    # Only import for type hints, not at runtime to avoid circular imports
    from shared.messaging import MessagingService

class OrgServiceCountryCode(Enum):
    ISRAEL = "IL"

class OrgServiceEventType(Enum):
    IFA = "football"
    IHA = "handball"

class OrgServiceBase(ABC):
    def __init__(self, logger:Logger, multiTenantSupport:MultiTenantSupport, cacheService:CacheService, handleUsers:HandleUsers, messagingService:'MessagingService', countryCode:Enum, eventType:Enum):
        self.logger = logger
        self.multiTenantSupport = multiTenantSupport
        self.cacheService = cacheService
        self.handleUsers = handleUsers
        self.messagingService = messagingService
        self.countryCode = countryCode
        self.eventType = eventType

        self.baseUrl = None

        self.latencyFactor = float(os.getenv('latencyFactor', '1'))

        self.globalRefereesByName = handleUsers.globalRefereesByName
        self.refereesByGuid = handleUsers.refereesByGuid
        self.refereesByMobile = handleUsers.refereesByMobile
        self.refereesByRefId = handleUsers.refereesByRefId
        self.globalRefereesByMobile = handleUsers.globalRefereesByMobile
        # id(BrowserContext) -> hostnames already primed via FlareSolverr for this session
        self._flare_warmed_hosts_by_context: dict[int, set[str]] = {}

    @staticmethod
    def _flare_section() -> dict:
        try:
            merged = ConfigManager.get_merged_file_config()
            sec = merged.get('FlareSolverr')
            return sec if isinstance(sec, dict) else {}
        except FileNotFoundError:
            return {}

    @staticmethod
    def _flare_enabled_source():
        if 'USE_FLARESOLVERR' in os.environ:
            return os.environ['USE_FLARESOLVERR']
        return OrgServiceBase._flare_section().get('enabled', False)

    @staticmethod
    def _flare_url_str() -> str:
        if 'FLARESOLVERR_URL' in os.environ:
            return (os.environ.get('FLARESOLVERR_URL') or '').strip()
        return str(OrgServiceBase._flare_section().get('url') or '').strip()

    @staticmethod
    def _flare_max_timeout_ms() -> int:
        if 'FLARESOLVERR_MAX_TIMEOUT_MS' in os.environ:
            ms_raw = os.environ.get('FLARESOLVERR_MAX_TIMEOUT_MS') or '120000'
        else:
            ms_raw = OrgServiceBase._flare_section().get('maxTimeoutMs', 120000)
        try:
            return int(str(ms_raw).strip() or '120000')
        except ValueError:
            return 120000

    @staticmethod
    def _flare_use_truthy(raw) -> bool:
        if raw is None:
            return False
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip()
        if not s:
            return False
        sl = s.lower()
        if sl in ('1', 'true', 'yes', 'on'):
            return True
        if sl in ('0', 'false', 'no', 'off', 'none'):
            return False
        return s == 'True'

    @staticmethod
    def flare_solverr_enabled() -> bool:
        use_raw = OrgServiceBase._flare_enabled_source()
        url_raw = OrgServiceBase._flare_url_str()
        if not OrgServiceBase._flare_use_truthy(use_raw):
            return False
        return bool(url_raw)

    @staticmethod
    def flare_solverr_request_get(url: str) -> dict | None:
        """Call FlareSolverr v1 API (request.get). Returns the solution dict or None on failure."""
        base = OrgServiceBase._flare_url_str().rstrip('/')
        if not base:
            return None
        endpoint = f'{base}/v1'
        max_timeout_ms = OrgServiceBase._flare_max_timeout_ms()
        payload = {'cmd': 'request.get', 'url': url, 'maxTimeout': max_timeout_ms}
        req_timeout = max(30.0, max_timeout_ms / 1000.0 + 15.0)
        try:
            r = requests.post(endpoint, json=payload, timeout=req_timeout)
        except requests.RequestException as ex:
            logging.warning('FlareSolverr: request failed endpoint=%s err=%s', endpoint, ex)
            return None
        try:
            data = r.json()
        except ValueError:
            logging.warning(
                'FlareSolverr: non-JSON response status=%s body=%s',
                r.status_code,
                (r.text or '')[:500],
            )
            return None
        if data.get('status') != 'ok':
            logging.warning(
                'FlareSolverr: status=%s message=%s',
                data.get('status'),
                (data.get('message') or '')[:500],
            )
            return None
        sol = data.get('solution')
        if not isinstance(sol, dict):
            logging.warning('FlareSolverr: missing solution in response')
            return None
        return sol

    @staticmethod
    def _flare_cookie_to_playwright(c: dict) -> dict | None:
        name, value = c.get('name'), c.get('value')
        if not name or value is None:
            return None
        entry: dict = {'name': str(name), 'value': str(value), 'path': c.get('path') or '/'}
        domain = (c.get('domain') or '').strip()
        if domain:
            entry['domain'] = domain
        exp = c.get('expires')
        if exp is not None and exp != -1:
            try:
                exp_f = float(exp)
                if exp_f > 1e12:
                    exp_f /= 1000.0
                entry['expires'] = exp_f
            except (TypeError, ValueError):
                pass
        if c.get('httpOnly') is True:
            entry['httpOnly'] = True
        if c.get('secure') is True:
            entry['secure'] = True
        ss = c.get('sameSite')
        if isinstance(ss, str) and ss:
            ss_norm = ss.strip().lower().replace('-', '')
            mapping = {'strict': 'Strict', 'lax': 'Lax', 'none': 'None', 'norestriction': 'None'}
            if ss_norm in mapping:
                entry['sameSite'] = mapping[ss_norm]
        return entry

    @staticmethod
    async def apply_flare_solution_to_context(context: BrowserContext, solution: dict):
        """Apply FlareSolverr solution cookies and User-Agent to an existing Playwright context."""
        raw = solution.get('cookies') or []
        pw_cookies = []
        if isinstance(raw, list):
            for c in raw:
                if isinstance(c, dict):
                    conv = OrgServiceBase._flare_cookie_to_playwright(c)
                    if conv:
                        pw_cookies.append(conv)
        if pw_cookies:
            await context.add_cookies(pw_cookies)
        ua = (solution.get('userAgent') or '').strip()
        if ua:
            await context.set_extra_http_headers({'User-Agent': ua})

    async def _ensure_flare_solverr_warmed(self, page: Page, url: str):
        """Once per (browser context, hostname), fetch clearance via FlareSolverr and inject into Playwright."""
        if not OrgServiceBase.flare_solverr_enabled():
            if not hasattr(self, 'flare_solverr_enabled_logged') or not self.flare_solverr_enabled_logged:
                self.flare_solverr_enabled_logged = True
                self.logger.info(f'FlareSolverr: not enabled')
            return
        host = (urlparse(url).hostname or '').lower().strip()
        if not host:
            return
        ctx = page.context
        ck = id(ctx)
        warmed = self._flare_warmed_hosts_by_context.setdefault(ck, set())
        if host in warmed:
            return
        self.logger.info(f'FlareSolverr: solving for host={host} …')
        solution = await asyncio.to_thread(OrgServiceBase.flare_solverr_request_get, url)
        if not solution:
            self.logger.error(f'FlareSolverr: failed to solve for host={host} url={url}')
            return
        self.logger.info(f'FlareSolverr: solved for host={host} url={url} solution={solution}')
        await OrgServiceBase.apply_flare_solution_to_context(ctx, solution)
        warmed.add(host)
        st = solution.get('status')
        self.logger.info(f'FlareSolverr: primed host={host} http_status={st}')

    @staticmethod
    def _browser_proxy_config():
        """Playwright chromium.launch(proxy=...) config, or None for direct connection.

        Proxy URL resolution (first non-empty wins):
        - BROWSER_PROXY_SERVER — optional; use when Playwright egress should differ from PROXY_SERVER.
        - PROXY_SERVER — default browser proxy if BROWSER_PROXY_SERVER is unset.

        DISABLE_BROWSER_PROXY=1 — force no proxy even if the vars above are set (debug / no sidecar).
        """
        if os.getenv('DISABLE_BROWSER_PROXY', '').strip().lower() in ('1', 'true', 'yes', 'on'):
            return None
        raw = (os.getenv('BROWSER_PROXY_SERVER') or '').strip() or (os.getenv('PROXY_SERVER') or '').strip()
        if not raw or raw.lower() in ('0', 'false', 'off', 'none', 'disabled'):
            return None
        server = OrgServiceBase._normalize_playwright_proxy_server(raw)
        return {'server': server}

    @staticmethod
    def _normalize_playwright_proxy_server(server: str) -> str:
        """Map proxy URLs to schemes Chromium accepts for launch(proxy=...).

        curl/tailscale often use socks5h:// (proxy-side DNS). Chromium / Playwright expect socks5://
        and raise net::ERR_NO_SUPPORTED_PROXIES for socks5h://.
        """
        s = server.strip()
        sl = s.lower()
        if sl.startswith('socks5h://'):
            return 'socks5://' + s[9:]
        return s

    @staticmethod
    def _chromium_launch_args():
        """Shared Chromium flags for Playwright; tune via env where noted."""
        args = [
            '--disable-gpu',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-setuid-sandbox',
            '--mute-audio',
            # Reduces automation fingerprinting (use with playwright-stealth on context)
            '--disable-blink-features=AutomationControlled',
        ]
        # Default: no --single-process (more processes, fewer pthread_create / thread-limit failures in Docker).
        # Set CHROMIUM_SINGLE_PROCESS=1 to save RAM on tiny hosts (may hit EAGAIN under load).
        if os.getenv('CHROMIUM_SINGLE_PROCESS', '0').strip().lower() in ('1', 'true', 'yes', 'on'):
            args.insert(2, '--single-process')
        return args

    @staticmethod
    def _chromium_launch_kwargs(headless, proxy_config):
        """kwargs for playwright.chromium.launch — ignore automation default, optional real Chrome."""
        kwargs = {
            'headless': headless,
            'ignore_default_args': ['--enable-automation'],
            'args': OrgServiceBase._chromium_launch_args(),
        }
        # Installed Google Chrome / Edge (better TLS fingerprint than bundled Chromium). e.g. PLAYWRIGHT_BROWSER_CHANNEL=chrome
        channel = os.getenv('PLAYWRIGHT_BROWSER_CHANNEL', '').strip()
        if channel:
            kwargs['channel'] = channel
        if proxy_config is not None:
            kwargs['proxy'] = proxy_config
        return kwargs

    _LAUNCH_BROWSER_PROXY_UNSPECIFIED = object()

    async def launchBrowser(
        p: async_playwright,
        headless=True,
        useProxy=False,
        proxy_config=_LAUNCH_BROWSER_PROXY_UNSPECIFIED,
    ):
        # Support routing browser traffic through a proxy when running on EC2/cloud
        # (ref.football.org.il blocks AWS datacenter IPs — use a residential proxy to bypass)
        # Set PROXY_SERVER or BROWSER_PROXY_SERVER for outbound proxy (see _browser_proxy_config).
        # Pass proxy_config explicitly to reuse the dict from _browser_proxy_config() without a second env read.
        if proxy_config is OrgServiceBase._LAUNCH_BROWSER_PROXY_UNSPECIFIED:
            proxy_config = OrgServiceBase._browser_proxy_config() if useProxy else None
        logging.info(f"launchBrowser proxy_config: {proxy_config}")
        launch_kwargs = OrgServiceBase._chromium_launch_kwargs(headless=headless, proxy_config=proxy_config)
        launch_timeout = float((os.getenv('PLAYWRIGHT_LAUNCH_TIMEOUT_SECONDS') or '0').strip() or 0)
        launch_coro = p.chromium.launch(**launch_kwargs)
        if launch_timeout > 0:
            browser = await asyncio.wait_for(launch_coro, timeout=launch_timeout)
        else:
            browser = await launch_coro

        '''
        browser.on('disconnected', lambda: self.handleBrowserEvents(browser=browser, msg='Browser disconnected'))
        browser.on('page', lambda page: self.handleBrowserEvents(browser=browser, msg=f'Page opened: {page.url}'))
        browser.on('request', lambda request: self.handleBrowserEvents(browser=browser, msg=f'Request: {request.url}'))
        browser.on('response', lambda response: self.handleBrowserEvents(browser=browser, msg=f'Response: {response.url}'))
        browser.on('console', lambda msg: self.handleBrowserEvents(browser=browser, msg=f'Console: {msg.text}'))
        browser.on('crash', lambda: self.handleBrowserEvents(browser=browser, msg='Browser crashed'))
        browser.on('close', lambda: self.handleBrowserEvents(browser=browser, msg='Browser closed'))
        '''
        return browser

    @staticmethod
    async def async_playwright_start():
        """Start Playwright driver (subprocess). Single attempt; callers may catch and handle failures."""
        return await async_playwright().start()

    @staticmethod
    async def async_playwright_stop_safe(pw):
        if pw is None:
            return
        try:
            await pw.stop()
        except Exception:
            pass

    @staticmethod
    @asynccontextmanager
    async def playwright_driver_context():
        """async_playwright().start() with safe stop() on exit."""
        pw = await OrgServiceBase.async_playwright_start()
        try:
            yield pw
        finally:
            await OrgServiceBase.async_playwright_stop_safe(pw)

    async def getLocator(self, parent, selector = None, nonSingle = False):
        locator = parent.locator(selector) if selector else parent
        cnt = await locator.count()
        if cnt > 0:
            if cnt == 1 or nonSingle and cnt > 0 or not selector:
                for i in range(await locator.count()):
                    locatorNth = locator.nth(i)
                    await locatorNth.evaluate("element => element.style.backgroundColor = 'red'")
                    children = await locatorNth.locator('tr, td').all()
                    for child in children:
                        await child.evaluate("element => element.style.backgroundColor = 'red'")
                    await locatorNth.wait_for(state='visible')
                    await locatorNth.scroll_into_view_if_needed()
            return locator
        return None

    async def createContext(browser):
        locale = (os.getenv('BROWSER_LOCALE') or 'he-IL').strip() or 'he-IL'
        timezone_id = (os.getenv('BROWSER_TIMEZONE') or 'Asia/Jerusalem').strip() or 'Asia/Jerusalem'
        viewport = None
        vw = os.getenv('BROWSER_VIEWPORT_WIDTH', '').strip()
        vh = os.getenv('BROWSER_VIEWPORT_HEIGHT', '').strip()
        if vw.isdigit() and vh.isdigit():
            viewport = {'width': int(vw), 'height': int(vh)}
        ctx_opts = {
            'device_scale_factor': 1,
            'java_script_enabled': True,
            'bypass_csp': True,
            'ignore_https_errors': True,
            'locale': locale,
            'timezone_id': timezone_id,
        }
        if viewport:
            ctx_opts['viewport'] = viewport
        context = await browser.new_context(**ctx_opts)
        return context

    def handleBrowserEvents(self, browser, msg):
        self.logger.warning(msg)

    async def gotoUrl(self, page: Page, url, timeout = None, level = None, refereeDetail = None):
        """Navigate and return the page used for navigation (same page instance; no automatic new tab on errors)."""
        helpers.stopwatchStart(f'{url}Url')
        url = url.replace('//?', '?')
        work = page
        successful = True
        status_code = None
        for i in range(2):
            successful = False
            try:
                w0 = (os.getenv('BROWSER_GOTO_WAIT_UNTIL', 'load') or 'load').strip()
                w1 = (os.getenv('BROWSER_GOTO_WAIT_UNTIL_RETRY', 'domcontentloaded') or 'domcontentloaded').strip()
                wait_until = w0 if i == 0 else w1
                nav_to = timeout
                if nav_to is None:
                    nav_to = int(os.getenv('BROWSER_GOTO_TIMEOUT_MS', '60000'))

                await self._ensure_flare_solverr_warmed(work, url)
                response = await work.goto(url, timeout=nav_to, wait_until=wait_until)

                status_code = response.status if response else None
                successful = status_code is not None and 200 <= status_code < 300
                self.logger.debug(f'gotoUrl {url} successful={successful} status_code={status_code}')
                if successful:
                    break
                else:
                    await helpers.takeScreenshot(page=work, tag=f'gotoUrl_{status_code}')

                is_blocked = await work.locator('text="Why have I been blocked?"').is_visible()
                if is_blocked and False:
                    print("blocked. The site's security is very strong.")
                    from playwright_stealth import Stealth
                    stealth = Stealth()
                    await stealth.apply_stealth_async(work.context)
                    if timeout:
                        response = await work.goto(url, timeout=timeout, wait_until=wait_until)
                    else:
                        response = await work.goto(url, wait_until=wait_until)
                    is_blocked = await work.locator('text="Why have I been blocked?"').is_visible()
                    if is_blocked:
                        print("Still blocked using stealth. The site's security is very strong.")
            
            except Exception as ex:
                err = str(ex)
                ex_type = type(ex).__name__
                await helpers.takeScreenshot(page=work, tag='gotoUrl')
                target_closed = (
                    'TargetClosed' in ex_type
                    or 'has been closed' in err.lower()
                )
                crash_recoverable = i == 0 and ('crash' in err.lower() and not target_closed)
                if target_closed and i == 0:
                    shared_batch = False
                    try:
                        from shared import playwright_shared_browser as _psb
                        shared_batch = _psb.in_shared_referee_batch()
                    except Exception:
                        shared_batch = False
                    if shared_batch:
                        self.logger.warning(
                            f'Navigation target closed ({ex_type}) with shared browser — not opening a new tab. '
                            f'url={url} err={err[:500]}'
                        )
                        raise
                    self.logger.warning(
                        f'Navigation failed during goto ({ex_type}); target closed — closing browser (no new tab). '
                        f'If this repeats: BROWSER_GOTO_WAIT_UNTIL=domcontentloaded, more memory, CHROMIUM_SINGLE_PROCESS=0. '
                        f'url={url} err={err[:500]}'
                    )
                    try:
                        ctx: BrowserContext = work.context
                        br = ctx.browser if ctx else None
                        if br and br.is_connected():
                            await br.close()
                    except Exception:
                        pass
                    raise
                if crash_recoverable:
                    self.logger.warning(
                        f'Navigation failed during goto ({ex_type}); not opening a new tab. '
                        f'If this repeats: BROWSER_GOTO_WAIT_UNTIL=domcontentloaded, more memory, CHROMIUM_SINGLE_PROCESS=0. '
                        f'url={url} err={err[:500]}'
                    )
                    raise
                elif 'Timeout' in err:
                    self.logger.info(f'{url} {ex}')
                elif 'ERR_PROXY_CONNECTION_FAILED' in err:
                    self.logger.error(
                        'gotoUrl: Chromium cannot connect to the configured proxy (ERR_PROXY_CONNECTION_FAILED). '
                        'The host:port in BROWSER_PROXY_SERVER / PROXY_SERVER must be reachable from inside the '
                        'gw container (same Docker network / DNS name, firewall, SOCKS actually listening). '
                        'This compose file does not define a tailscale service — if you use socks5://tailscale:1055, '
                        'add a Tailscale (or other SOCKS) sidecar on refereex_shared_net or point PROXY_SERVER at a '
                        'reachable IP/hostname. To bypass the proxy: DISABLE_BROWSER_PROXY=1 (direct egress may be '
                        'blocked from some cloud IPs). '
                        f'url={url} status_code={status_code}',
                        ex,
                    )
                else:
                    self.logger.error(f'gotoUrl {url} status_code={status_code}', ex)
        
        if not successful:
            raise Exception(f"gotoUrl failed: {status_code}")
        
        await self.scroll_to_bottom(work)
        helpers.stopwatchStop(f'{url}Url', level=level)
        return work

    async def getBaseWazeRoute(self, from_latitude, from_longitude, to_latitude, to_longitude, arriveAt=None, browser=None):
        async with async_playwright() as p:
            browser = await OrgServiceBase.launchBrowser(p=p, headless=eval(os.getenv('browserHeadless') or 'True'))
            context = await OrgServiceBase.createContext(browser=browser)
            stealth = Stealth()
            await stealth.apply_stealth_async(context)
            page = await context.new_page()
            total_seconds = None
            total_meters = None
            
            try:
                waze_url = f'https://www.waze.com/ul?ll={to_latitude},{to_longitude}&navigate=yes&from={from_latitude},{from_longitude}'
                if arriveAt:
                    arriveAtTs = int(arriveAt.timestamp()) * 1000
                    waze_url = f'{waze_url}&time={arriveAtTs}&reverse=yes'
                            #https://www.waze.com/en-GB/live-map/directions?navigate=yes&to=ll.32.0429027%2C34.7937824&from=ll.32.0771918%2C34.8101153&time=1735084800000&reverse=yes
                else:
                    pass

                # Navigate to the URL
                page = await self.gotoUrl(page=page, url=waze_url)

                if False:
                    await page.wait_for_selector(selector=".is-fastest", timeout=7000)

                # get duration
                route_element_div = None
                is_fastest_element_div = await page.query_selector_all("div.wm-routes-item-desktop__header:has(ul li.is-fastest)")
                if is_fastest_element_div and len(is_fastest_element_div) == 1:
                    route_element_div = is_fastest_element_div[0]
                else:
                    elements = await page.query_selector_all("div.wm-routes-item-desktop__header")
                    if elements and len(elements) > 0:
                        route_element_div = elements[0]
                if route_element_div:
                    span = await route_element_div.query_selector("span[title]")
                    if span:
                        title_secs = await span.get_attribute("title")    
                        total_seconds = int(title_secs.replace(",", "").replace("s", ""))

                # get distance
                is_fastest_element_div = await page.query_selector_all("div.wm-routes-item-desktop__details:has(ul li.is-fastest)")
                if is_fastest_element_div and len(is_fastest_element_div) == 1:
                    route_element_div = is_fastest_element_div[0]
                else:
                    elements = await page.query_selector_all("div.wm-routes-item-desktop__details")
                    if elements and len(elements) > 0:
                        route_element_div = elements[0]
                if route_element_div:
                    span = await route_element_div.query_selector("span[title]")
                    if span:
                        title_meters = await span.get_attribute("title")    
                        total_meters = int(title_meters.replace(",", "").replace("m", ""))

            except Exception as ex:
                self.logger.error(f"getWazeRouteDuration: Error extracting route time:", ex)
            finally:
                await browser.close()
            
            return total_seconds, total_meters

    async def scroll_to_bottom(self, page):
        try:
            for i in range(0, 10):
                await page.evaluate(f"""() => {{window.scrollTo(0, {i*20} );}}""")
                await asyncio.sleep(25/1000)
        except Exception as e:
            pass

    def fixNameQuote(self, name):
        name = name.replace("׳","'")
        return name

    @abstractmethod
    def setFetchDates(self, refereeData):
        pass

    @abstractmethod
    def getPk(self, objType, obj):
        pass

    @abstractmethod
    async def login(self, refereeDetail, page) -> tuple[bool, str]:
        pass

    @abstractmethod
    async def logout(self, refereeDetail, page):
        pass

    @abstractmethod
    async def changePassword(self, refereeDetail, targetRefereeDetail,page) -> tuple[bool, str]:
        pass

    @abstractmethod
    async def collectItemsForAssigner(self, tenantKey, objType, refereeData, page):
        pass            

    @abstractmethod
    async def parseListForReferee(self, tenantKey, objType, refereeData, page):
        pass

    async def getListForReferee(self, tenantKey, objType, refereeData, page) -> bool:
        if objType not in refereeData:
            refereeData[objType] = {}

        parsedList = await self.parseListForReferee(tenantKey=tenantKey, objType=objType, refereeData=refereeData, page=page)
        if parsedList == None:
            return False
        
        now = helpers.localNow()
        currentList = {}
        if objType == 'games':
            for gamePk, parsedItem in parsedList.items():
                if (
                    parsedItem.get('date').date() < refereeData[objType]['fromDate']
                    or parsedItem.get('date').date() > refereeData[objType]['toDate']
                ):
                    continue
                prevItem = refereeData[objType]['prevList'].get(gamePk)
                parsedItem['state'] = prevItem and prevItem.get('date') < now and prevItem.get('state', 'active') or 'active'
                currentList[gamePk] = parsedItem

        refereeData[objType]['currentList'] = currentList
        return True
    
    @abstractmethod
    async def createGameInRefSix(self, page, username, password, gameDetail):
        pass

    @abstractmethod
    async def generatePostGameUpdateTemplate(self, gameDetail):
        pass

    async def getPostGameUpdateTemplate(self, refId, gameId):
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        if gameDetail is None or refId not in gameDetail.get('mainReferees', []):
            return None

        msg = await self.generatePostGameUpdateTemplate(gameDetail=gameDetail)
        
        url = self.messagingService.getWhatsAppUrl(text=msg)
        return url

    @abstractmethod
    async def getCupsList(self):
        pass

    @abstractmethod
    async def getLeaguesList(self):
        pass

    @abstractmethod
    async def getLeagueName(self, page, tournamentUrl):
        pass

    @abstractmethod
    async def refreshLeaguesTablesByTournament(self, page, tournament, section):
        pass

    @abstractmethod
    async def refreshLeaguesTables(self, tenantKey, tournamentName):
        pass
    
    async def refreshLeaguesTables1(self, tenantKey, tournamentName):
        async with async_playwright() as p:
            browser = await OrgServiceBase.launchBrowser(p=p, headless=eval(os.getenv('browserHeadless') or 'True'))
            context = await OrgServiceBase.createContext(browser=browser)
            stealth = Stealth()
            await stealth.apply_stealth_async(context)
            page = await context.new_page()
            tournaments = self.cacheService.getTournaments(tenantKey=tenantKey)
            for _tournamentName, _tournament in tournaments.items():
                if tournamentName and tournamentName != _tournamentName:
                    continue
                if _tournament.get('section'):
                    section = self.cacheService.get_section_by_name(tenantKey=tenantKey, sectionName=_tournament['section'])
                    if section:
                        await self.refreshLeaguesTablesByTournament(page=page, tournament=_tournament, section=section)
            
            await browser.close()

    @abstractmethod
    async def getTournamentGamesUrl(self, page, tournament, round, fixture, fromFixture = None) -> list:
        pass

    @abstractmethod
    async def refreshTournamentGame(self, tenantKey, page, tournamentName, gameDetail) -> bool:
        pass
    
    async def refreshTournamentGames(self, tenantKey, tournamentName = None, round = None, fixture = None, fromFixture = None, fetchGamesUrls = False, fetchGamesDetails = False, fetchReferees = False, tournamentTypes:list = ['league'], instance:int = None) -> (bool, str):
        def changeTeamName(gameDetail:dict, oldTeamName:str, newTeamName:str):
            oldGamePk = gameDetail.get('gamePk')
            if oldTeamName not in gameDetail['gamePk']:
                return gameDetail
            newGamePk = oldGamePk.replace(oldTeamName, newTeamName)
            gameDetail['gamePk'] = newGamePk
            gameDetail['gameTitle'] = gameDetail['gameTitle'].replace(oldTeamName, newTeamName)
            if gameDetail.get('groupName'):
                gameDetail['groupName'] = gameDetail['groupName'].replace(oldTeamName, newTeamName)
            gameDetail['homeTeamName'] = gameDetail['homeTeamName'].replace(oldTeamName, newTeamName)
            gameDetail['guestTeamName'] = gameDetail['guestTeamName'].replace(oldTeamName, newTeamName)
            result = self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=newGamePk, value=gameDetail)
            self.cacheService.deleteTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=oldGamePk)
            
            for refId in gameDetail.get('refereeIds', []):
                gameReferee = self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=refId, gamePk=oldGamePk)
                if gameReferee:
                    gameReferee['gamePk'] = newGamePk
                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=newGamePk, value=gameReferee)
                    self.cacheService.deleteRefereeGame(tenantKey=tenantKey, refId=refId, gamePk=oldGamePk)

            return result[0]

        def checkCurrentTournamentGames(tournamentName, tournamentGames):
            oldTeamName = 'הפ\' פתח תקוה שלומי וורצל'
            newTeamName = 'הפ\' פ"ת שלומי וורצל'
            foundGamePks = set([ gameDetail.get('gamePk') for gameDetail in tournamentGames ])
            currentTournamentGames = self.cacheService.getTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName)
            if not currentTournamentGames:
                return
            for gamePk, gameDetail in currentTournamentGames.items():
                updatedGameDetail = changeTeamName(gameDetail=gameDetail, oldTeamName=oldTeamName, newTeamName=newTeamName)
                updatedGamePk = updatedGameDetail.get('gamePk')
                if updatedGamePk not in foundGamePks:
                    self.cacheService.deleteTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=updatedGamePk)

        try:
            if tournamentName and False:
                tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
                if not tournament or not tournament.get('href'):
                    return False, 'no url for tournament'

            self.logger.info(f'refreshTournamentGames tenantKey={tenantKey} tournamentName={tournamentName} round={round} fixture={fixture} fetchGameDetails={fetchGamesDetails}')
            result = False
            message = ''
            totalGames = 0
            totalGamesUpdated = 0
            totalGamesWithNoUpdate = 0
            totalGamesAdded = 0
            async with async_playwright() as p:
                browser = await OrgServiceBase.launchBrowser(p=p, headless=eval(os.getenv('browserHeadless') or 'True'), useProxy=False)
                context = await OrgServiceBase.createContext(browser=browser)
                stealth = Stealth()
                await stealth.apply_stealth_async(context)
                context.set_default_timeout(3000)
                context.set_default_navigation_timeout(3000)
                page = await context.new_page()
                if tournamentName:
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName, forceReload=True)
                    tournaments = {tournamentName: tournament}
                else:
                    tournaments = self.cacheService.getTournaments(tenantKey=tenantKey, forceReload=True)
                _tournametGames = {}
                
                for _tournamentName, _tournament in tournaments.items():
                    if _tournament.get('tournament') not in tournamentTypes:
                        continue
                    if False and 'וינר' not in _tournamentName:
                        continue
                    if instance is not None and int(_tournament.get('leagueId') or _tournament.get('nationalCupId') or '0') % 2 != instance:
                        continue
                    section = self.cacheService.get_section_by_name(tenantKey=tenantKey, sectionName=_tournament['section'])
                    scrapResults = 'ילד' not in _tournamentName
                    if fetchGamesUrls:
                        tournamentGamesUrl = await self.getTournamentGamesUrl(page=page, tournament=_tournament, round=round, fixture=fixture, fromFixture=fromFixture)
                        totalGamesPerTournament = 0
                        totalGamesUpdatedPerTournament = 0
                        totalGamesWithNoUpdatePerTournament = 0
                        totalGamesAddedPerTournament = 0
                        if tournamentGamesUrl:
                            tournamentGames = {}
                            totalGamesPerTournament += len(tournamentGamesUrl)
                            result = True
                            gamePks = list(game['gamePk'] for game in tournamentGamesUrl)
                            tournamentGames = self.cacheService.getTournamentGames(tenantKey=tenantKey, tournamentName=_tournamentName, gamePk=gamePks)
                            for gameDetailUrl in tournamentGamesUrl:
                                gamePk = gameDetailUrl.get('gamePk')
                                gameDetail:dict = tournamentGames.get(gamePk)
                                isNewGame = False
                                if gameDetail:
                                    'ליגת ילדים ג\' שרון#ליגת ילדים ג\' שרוןמכבי ת"א לייבו  מ.ס.קדימה צורן "צו פיוס"1'
                                    gameDetail['date'] = gameDetailUrl['date']
                                    gameDetail['field'] = gameDetailUrl['field']
                                    gameDetail['homeTeamId'] = gameDetailUrl['homeTeamId']
                                    gameDetail['homeTeamName'] = gameDetailUrl['homeTeamName']
                                    gameDetail['guestTeamId'] = gameDetailUrl['guestTeamId']
                                    gameDetail['guestTeamName'] = gameDetailUrl['guestTeamName']
                                    gameDetail['internalGameId'] = gameDetailUrl['internalGameId']
                                    gameDetail['url'] = gameDetailUrl['url']
                                    gameResult = helpers.merge_nested_dicts(gameDetail.get('gameResult', {}), gameDetailUrl['gameResult'])
                                    if (
                                        not gameDetail.get('gameResult') or 
                                        not gameResult or
                                        jsonHelper.save_to_json(gameDetail.get('gameResult')) != jsonHelper.save_to_json(gameResult)
                                    ):
                                        gameDetail['gameResult'] = gameResult
                                        gameDetail['gameResult']['updatedAt'] = helpers.localNow()
                                else:
                                    isNewGame = True
                                    gameDetail = gameDetailUrl
                                    gameDetail['id'] = str(uuid.uuid4())[:8]
                                    gameDetail['groupName'] = f'{gameDetail["tournamentName"]} {gameDetail["gameTitle"]}'
                                    if gameDetail.get('gameResult'):
                                        gameDetail['gameResult']['updatedAt'] = helpers.localNow()
                                        
                                setResult = self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=_tournamentName, gamePk=gamePk, value=gameDetail)
                                if isNewGame:
                                    totalGamesAddedPerTournament += 1
                                else:
                                    if setResult[1]:
                                        gameDetail = setResult[0]
                                        totalGamesUpdatedPerTournament += 1
                                    else:
                                        totalGamesWithNoUpdatePerTournament += 1
                                tournamentGames[gamePk] = gameDetail

                            totalGames += totalGamesPerTournament
                            totalGamesUpdated += totalGamesUpdatedPerTournament
                            totalGamesWithNoUpdate += totalGamesWithNoUpdatePerTournament
                            totalGamesAdded += totalGamesAddedPerTournament
                            self.logger.info(f'refreshTournamentGamesUrl instance={instance} tenantKey={tenantKey} tournamentName={_tournamentName} totalGames={totalGamesPerTournament} totalGamesUpdated={totalGamesUpdatedPerTournament} totalGamesWithNoUpdate={totalGamesWithNoUpdatePerTournament} totalGamesAdded={totalGamesAddedPerTournament}')
                            
                            _tournament['lastFetchGamesUrls'] = helpers.localNow()
                            self.cacheService.setTournament(tenantKey=tenantKey, tournamentName=_tournamentName, value=_tournament)                    
                            _tournametGames[_tournamentName] = tournamentGames

                    if fetchGamesDetails:
                        if not fetchGamesUrls:
                            tournamentGames = self.cacheService.getTournamentGames(tenantKey=tenantKey, tournamentName=_tournamentName, forceReload=True)
                        else:
                            tournamentGames = _tournametGames.get(_tournamentName, {})
                        now = helpers.localNow()
                        for gamePk, gameDetail in tournamentGames.items():
                            now = helpers.localNow()
                            if not gameDetail.get('date') or gameDetail.get('homeTeamName') == 'חופשית' or gameDetail.get('guestTeamName') == 'חופשית':
                                self.cacheService.deleteTournamentGame(tenantKey=tenantKey, tournamentName=_tournamentName, gamePk=gameDetail.get('gamePk'))
                                continue
                            if not gameDetail.get('date'):
                                continue
                            if gameDetail.get('date') > now:
                                continue
                            if False and not gameDetail.get('url'):
                                tmpTournamentGames = await self.getTournamentGamesUrl(page=page, tournament=_tournament, round=int(gameDetail.get('round', '0')), fixture=int(gameDetail.get('fixture', '0')))
                            if not (gameDetail.get('lastFetchGamesDetails') and gameDetail.get('lastFetchGamesDetails') > now - timedelta(days=7)):
                                if not gameDetail.get('squads') or scrapResults and not gameDetail.get('gameResult') or not gameDetail.get('referees'):
                                    refreshed = await self.refreshTournamentGame(tenantKey=tenantKey, page=page, tournamentName=_tournamentName, gameDetail=gameDetail)
                            if gameDetail.get('referees') and (not gameDetail.get('refereesUpdatedAt') or fetchReferees):
                                for referee in gameDetail.get('referees'):
                                    if referee.get('* phone'):
                                        refereeGame = {'date': gameDetail.get('date'), 'role': referee.get('role'), 'state': 'active', 'status': 'מאושר', 'tournamentName': _tournamentName }
                                        self.cacheService.setRefereeGameNew(tenantKey=tenantKey, mobileNo=referee.get('* phone'), gamePk=gameDetail.get('gamePk'), value=refereeGame)
                                gameDetail['refereesUpdatedAt'] = now
                                self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=_tournamentName, gamePk=gameDetail.get('gamePk'), value=gameDetail)
                        _tournament['lastFetchGamesDetails'] = now
                        self.cacheService.setTournament(tenantKey=tenantKey, tournamentName=_tournamentName, value=_tournament)

                    #checkCurrentTournamentGames(tournamentName=_tournamentName, tournamentGames=tournamentGames)

                await browser.close()

                message = f'refreshTournamentGames instance={instance} tenantKey={tenantKey} round={round} fixture={fixture} fetchGameDetails={fetchGamesDetails} totalGames={totalGames} totalGamesUpdated={totalGamesUpdated} totalGamesWithNoUpdate={totalGamesWithNoUpdate} totalGamesAdded={totalGamesAdded}'
                self.logger.info(message)
                return result, message

        except Exception as ex:
            self.logger.error(f'refreshTournamentGames', ex)
            return result, str(ex)

    @abstractmethod
    async def approveGame(self, refereeData, gameId, page, statusCell=None) -> tuple[bool, str]:
        pass

    @abstractmethod
    async def declineGame(self, refereeData, gameId, page, statusCell=None) -> tuple[bool, str]:
        pass

    @abstractmethod
    async def beforeGameUpdateByOrgService(self, refereeDetail, gameId, data, page) -> tuple[bool, str]:
        pass

    @abstractmethod
    async def afterGameUpdateByOrgService(self, refereeDetail, gameId, data, page):
        pass

    async def postGameUpdate(self, refereeDetail, gameId, data, page) -> tuple[bool, str]:
        try:
            self.logger.info(f'postGameUpdate refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')

            entryUrl = page.url
            result, message = await self.beforeGameUpdateByOrgService(refereeDetail=refereeDetail, gameId=gameId, data=data, page=page)
            if not result:
                return False, message
            
            if data:
                iteration = 0
                dataLeft = helpers.safeClone(data)
                while dataLeft:
                    iteration += 1
                    if iteration > 3:
                        break
                    processedSelectors = []
                    for selector, value in dataLeft.items():
                        if selector.endswith('!'):
                            continue
                        locators = page.locator(selector.split('@')[0])
                        locatorCount = await locators.count()
                        occurence = int(selector.split('@')[1]) if '@' in selector else 0
                        locator = locators.nth(occurence)
                        is_visible = await locator.is_visible()
                        is_disabled = await locator.is_disabled()
                        if not is_visible or is_disabled:
                            continue
                        await self.getLocator(parent=locator)
                        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
                        if tag in ('input', 'textarea'):
                            await locator.fill(value)
                        elif tag == 'select':
                            selectOptions = locator.locator('option')
                            for k in range(await selectOptions.count()):
                                selectOption = selectOptions.nth(k)
                                selectOptionValue = await selectOption.get_attribute("value")
                                selectOptionText = await selectOption.text_content()
                                if value in selectOptionText:
                                    await locator.select_option(value=selectOptionValue)
                                    await asyncio.sleep(300/1000)
                                    break

                        processedSelectors.append(selector)

                    for selector in processedSelectors:
                        dataLeft.pop(selector)

                    if not processedSelectors:
                        break
            
            await self.postGameReport(refereeDetail=refereeDetail, gameId=gameId, data=data, page=page)

            result = await self.afterGameUpdateByOrgService(refereeDetail=refereeDetail, gameId=gameId, data=data, page=page)

            if entryUrl != page.url and entryUrl != 'about:blank':
                page = await self.gotoUrl(page=page, url=entryUrl)
            if result:
                return True, 'success'

        except Exception as ex:
            self.logger.error(f'postGameUpdate', ex)

        return False, 'failed'

    @abstractmethod
    async def postGameReport(self, refereeDetail, gameId, data, page) -> tuple[bool, str]:
        pass

    async def wait_for_load_state(self, page, timeout=10000):
        try:
            await page.wait_for_load_state('networkidle', timeout=timeout)
        except Exception as ex:
            #self.logger.error(f'wait_for_load_state', ex)
            pass

    async def test(self, tenantKey, mobileNo):
        async with async_playwright() as p:
            browser = await OrgServiceBase.launchBrowser(p=p, headless=eval(os.getenv('browserHeadless') or 'True'))
            context = await OrgServiceBase.createContext(browser=browser)
            stealth = Stealth()
            await stealth.apply_stealth_async(context)
            page = await context.new_page()
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            tenant = self.cacheService.getTenants().get(tenantKey)
            now = helpers.localNow()
            refereeData = {
                'refereeDetail': refereeDetail,
                'refId': refereeDetail.get('refId'),
                'mobileNo': mobileNo,
                'games': {
                    'fromDate': now-timedelta(days=1),#tenant.get('fromDate'),
                    'toDate': now+timedelta(days=14)
                },
            }
            loginResult = await self.login(refereeDetail=refereeDetail, page=page)
            if loginResult:
                gameId = 'ec701a15'
                refereeDetail1 = self.handleUsers.refereesByMobile.get(tenantKey, {}).get('+972547799979')
                #await self.declineGame(refereeDetail=refereeDetail1, gameId=gameId, page=page)
                data = {
                    'homeTeamScore': '25',
                    'guestTeamScore': '20',
                    'gameReportFilePath': '/Users/guyshachar/Projects/Python/PythonProjects/apps/refPortal/HandballStaff/gameReportExample.pdf',
                    'gameNotes': 'Game completed successfully'
                }
                await self.postGameUpdate(refereeDetail=refereeDetail1, gameId=gameId, data=data, page=page, statusCell=None)
                #games = await self.getListForReferee(tenantKey=tenantKey, objType='games', refereeData=refereeData, page=page)
                
                pass
            await browser.close()
            pass

if __name__ == "__main__":
    from shared.appContainer import AppContainer
    container = AppContainer.getAppContainer()
    cacheService:CacheService = container.cache_service()
    from shared.handleTournaments import HandleTournaments
    handleTournaments:HandleTournaments = container.handle_tournaments()
    from shared.orgRelated.orgServiceFactory import OrgServiceFactory
    orgServiceFactory:OrgServiceFactory = container.orgServiceFactory()
    tenantKey = 'IL#football#2025-26'
    orgService:OrgServiceBase = orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)

    asyncio.run(orgService.refreshLeaguesTables(tenantKey=tenantKey))
    exit(0)
    #GameID=37510
    #PGid=51929
