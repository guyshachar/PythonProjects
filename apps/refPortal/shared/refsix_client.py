"""
RefSix (https://my.refsix.com/) browser automation client.

Creates a game/match in RefSix by:
1. Opening a browser and navigating to https://my.refsix.com/
2. Logging in with username and password
3. Going to the Fixtures menu and creating a new match from a game object

Requires: playwright, playwright-stealth (and playwright install chromium).
Selectors below are placeholders and must be updated to match the actual RefSix DOM.
"""

import os
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from playwright.async_api import Page

sys_path = Path(__file__).resolve().parent.parent
if str(sys_path) not in __import__("sys").path:
    __import__("sys").path.append(str(sys_path))

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from shared.db import CacheService
from shared.logger import Logger
import shared.helpers as helpers

# RefSix is a SPA: "networkidle" often never settles (polling/WebSockets) and burns task time.
# Override with REFSIX_GOTO_WAIT_UNTIL=domcontentloaded if needed.
_REFSIX_GOTO_WAIT = os.getenv("REFSIX_GOTO_WAIT_UNTIL", "load")


class RefSixClient:
    def __init__(self, logger:Logger, cacheService:CacheService):
        self.logger = logger
        self.cacheService = cacheService

        self.REFSIX_BASE_URL = "https://my.refsix.com/#/login"
        self.REFSIX_FIXTURES_URL = "https://my.refsix.com/#/fixture"
        self.REFSIX_SELECTORS = {
            "login_username": "input[name='username'], input[name='email'], input[type='email'], #username, input[ng-model='user.username']",
            "login_password": "input[name='password'], input[type='password'], #password",
            "login_submit": "button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('התחבר'), a:has-text('Login')",
            # Fixtures / navigation
            "menu_fixtures": "a:has-text('Matches'), a:has-text('Fixtures'), a:has-text('משחקים'), nav a:has-text('Fixtures'), [data-testid='menu-fixtures'], a[href*='fixture']",
            "new_match_btn": "button:has-text('New'), button:has-text('Add'), button:has-text('Create'), a:has-text('New Match'), a:has-text('הוסף משחק'), [data-testid='new-match']",
            # New match form (adjust to actual RefSix form fields)
            "form_home_team": "input[name='homeTeam'], input[name='home_team'], #homeTeam, [data-field='homeTeam']",
            "form_guest_team": "input[name='awayTeam'], input[name='guestTeam'], input[name='guest_team'], #guestTeam, [data-field='guestTeam']",
            "form_home_team_short": "input[name='homeShort']",
            "form_guest_team_short": "input[name='awayShort']",
            "form_date": "input[name='date'], input[name='gameDate'], input[type='date'], #date, input[name='fixtureDate']",
            "form_time": "input[name='time'], input[name='gameTime'], input[type='time'], #time",
            "form_venue": "input[name='venue'], input[name='field'], select[name='venue'], #venue",
            "form_tournament": "input[name='tournament'], input[name='competition'], #tournament",
            "form_template": "select[ng-model='selectedTemplate'], select[name='template'], #template",
            "form_submit": "button[type='submit'], button:has-text('Save'), button:has-text('Create'), button:has-text('שמור')",
            # Match setup (fixture template) form
            "setup_team_size": "input#teamSize, input[name='teamSize']",
            "setup_subs_size": "input[name='subsSize']",
            "setup_periods_no": "select[name='periodsNo']",
            "setup_timing_period": "input[name^='timingsperiod']",
            "setup_timing_interval": "input[name^='timingsinterval']",
            "setup_extra_time": "select[name='et']",
            "setup_extra_time_half_length": "input[name='extraTimeHalfLength']",
            "setup_penalties": "select[name='pens']",
            "setup_goal_scorers": "select[ng-model='fixture.withGoalScorers']",
            "setup_sin_bin": "select[ng-model='fixture.sinBinSystem']",
            "setup_misconduct_code": "select[ng-model='fixture.misconductCodeId']",
        }

    def normalizeGameForRefsix(self, game: dict) -> dict:
        """
        Map refPortal game object to a flat dict for RefSix form fields.
        Handles both refPortal keys (gameTitle, gameDate, gameTime, etc.) and explicit home/guest/date/time/venue.
        """
        if not game:
            return {}
        # Parse gameTitle "Home - Guest" if home_team/guest_team not provided
        game_title = game.get("gameTitle") or ""
        if " - " in game_title:
            parts = game_title.split(" - ", 1)
            default_home, default_guest = parts[0].strip(), parts[1].strip()
        else:
            default_home = game.get("homeTeam") or ""
            default_guest = game.get("guestTeam") or ""
        # Date/time: support datetime object or string
        date_val = game.get("date") or game.get("gameDate")
        time_val = game.get("gameTime") or ""
        if hasattr(date_val, "strftime"):
            date_str = date_val.strftime("%d/%m/%Y")
            if hasattr(date_val, "hour") and not time_val:
                time_val = date_val.strftime("%H:%M")
        elif isinstance(date_val, str):
            date_str = date_val
        else:
            date_str = ""
        if hasattr(time_val, "strftime"):
            time_str = time_val.strftime("%H:%M")
        else:
            time_str = str(time_val) if time_val else ""
        return {
            "tenantKey": game.get("tenantKey"),
            "home_team": game.get("homeTeam") or default_home,
            "guest_team": game.get("guestTeam") or default_guest,
            "date": date_str,
            "time": time_str,
            "venue": game.get("fieldName") or game.get("venue") or "",
            "tournament_name": game.get("tournamentName") or game.get("tournament") or "",
        }


    async def _try_click_or_fill(self, page, selector_comma_sep: str, value: any = None, action: str = "fill"):
        """Try each comma-separated selector until one works. action: 'fill', 'type', or 'click'. Fill/type use character-by-character typing."""
        typing_delay = int(os.getenv("REFSIX_TYPING_DELAY_MS", "80"))
        post_tab_sleep = float(os.getenv("REFSIX_POST_TAB_SLEEP_S", "0.2"))
        selectors = [s.strip() for s in selector_comma_sep.split(",")]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if await loc.count() == 0:
                    continue
                await loc.wait_for(state="visible", timeout=8000)
                if action == "fill" and value is not None:
                    await loc.fill(value)
                elif action in ("type") and value is not None:
                    if isinstance(value, str):
                        value = [value]
                    for v in value:
                        await loc.press_sequentially(v, delay=typing_delay)
                        await asyncio.sleep(post_tab_sleep)
                        await loc.press("Tab")
                        await loc.wait_for(state="visible", timeout=post_tab_sleep)
                elif action == "click":
                    await loc.click()
                return True
            except Exception as ex:
                continue
        return False


    async def _login_refsix(self, page, username: str, password: str) -> bool:
        """Perform login on the current page. Returns True if login appears successful."""
        try:
            ok_user = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["login_username"], username, "fill")
            ok_pass = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["login_password"], password, "fill")
            if not ok_user or not ok_pass:
                self.logger.warning("RefSix login: could not find username or password fields. Update REFSIX_SELECTORS.")
                return False
            await self._try_click_or_fill(page, self.REFSIX_SELECTORS["login_submit"], action="click")
            await asyncio.sleep(3000/1000)
            return True
        except Exception as e:
            self.logger.error(f"RefSix login error: {e}")
            return False


    async def _open_fixtures_and_click_new_match(self, page, navigation_timeout_ms: int) -> bool:
        """Open Fixtures menu and click New Match. Returns True if successful."""
        try:
            # Avoid redundant full reload if we are already on the fixtures route (saves several seconds).
            if "#/fixture" not in (page.url or ""):
                await page.goto(
                    self.REFSIX_FIXTURES_URL,
                    wait_until=_REFSIX_GOTO_WAIT,
                    timeout=navigation_timeout_ms,
                )
            ok = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["menu_fixtures"], action="click")
            if not ok:
                self.logger.warning("RefSix: could not find Fixtures menu. Update REFSIX_SELECTORS.")
                return False
            await asyncio.sleep(500/1000)
            ok_new = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["new_match_btn"], action="click")
            if not ok_new:
                self.logger.warning("RefSix: could not find New Match button. Update REFSIX_SELECTORS.")
                return False
            await asyncio.sleep(500/1000)
            return True
        except Exception as ex:
            self.logger.error(f"RefSix open fixtures / new match error: {ex}")
            return False


    async def _fill_new_match_form(self, page, game_flat: dict) -> bool:
        """Fill the new match form with game_flat (home_team, guest_team, date, time, venue, tournament_name)."""
        try:
            result = None
            if game_flat.get("home_team"):
                result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_home_team"], game_flat["home_team"], "fill")
            if game_flat.get("guest_team"):
                result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_guest_team"], game_flat["guest_team"], "fill")
            
            home_short_locator = page.locator(self.REFSIX_SELECTORS["form_home_team_short"]).first
            home_team_short = await home_short_locator.input_value() if home_short_locator else ''
            away_short_locator = page.locator(self.REFSIX_SELECTORS["form_guest_team_short"]).first
            away_team_short = await away_short_locator.input_value() if away_short_locator else ''
            if home_team_short == away_team_short:            
                await away_short_locator.fill(away_team_short[:2] + '_')
            
            datetime_value = ''
            '''
            <input type="datetime-local" ng-model="fixture.date" ng-disabled="fixture.integration" name="fixtureDate" class="ng-pristine ng-untouched ng-valid ng-not-empty" aria-invalid="false" style="">
            '''
            #if game_flat.get("time"):
            if game_flat.get("date"):
                datetime_value = [f'{game_flat["date"].replace('/', '')}', f'{game_flat["time"].replace(':', '')}']
                result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_date"], datetime_value, "type")
            if result is None:
                self.logger.error(f"RefSix fill form error: date is required")
                return False
            if game_flat.get("venue"):
                result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_venue"], game_flat["venue"], "fill")
            if game_flat.get("tournament_name"):
                result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_tournament"], game_flat["tournament_name"], "fill")
                if result:
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=game_flat["tenantKey"], tournamentName=game_flat["tournament_name"])
                    if tournament:
                        rules = self.cacheService.get_rule_by_name(tenantKey=game_flat["tenantKey"], ruleName=tournament.get('rules'))
                        if rules:
                            result = await self._try_click_or_fill(page, 'h2[ng-click="matchSetupOpened = true"]', action="click")
                            await self.fill_match_setup(rules, page)
                            await asyncio.sleep(250/1000)
                            #result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_template"], rules.get('ruleName'), "fill")
            result = await self._try_click_or_fill(page, self.REFSIX_SELECTORS["form_submit"], action="click")
            await asyncio.sleep(800/1000)
            return True
        except Exception as e:
            self.logger.error(f"RefSix fill form error: {e}")
            return False

    async def fill_match_setup(self, rules: dict, page) -> bool:
        """
        Example rules object:
            rules_example = {
                "templateName": "נערים ב׳/ג׳",           # or "ruleName" – template dropdown label
                "teamSize": 7,
                "subsNo": 5,
                "periodsNo": 2,                          # 1=one period, 2=halves, 3=thirds, 4=quarters
                "gameGrossTime": 50,                     # total minutes; split by periodsNo if no periodLengths
                "periodLengths": [25, 25],               # optional: minutes per period (overrides gameGrossTime)
                "intervalLengths": [5],                  # optional: minutes per interval (or interval1, interval2)
                "extraTimeAvailable": False,
                "extraTimeHalfLength": None,
                "penaltiesAvailable": True,
                "withGoalScorers": True,
                "sinBinSystem": "none",                  # "none" | "systemA" | "systemB"
                "misconductCodeId": "custom",             # e.g. "custom", "fifa", "england"
            }
        """
        if not rules:
            return True
        try:
            # Template name (select by visible option label; options have value="object:908" etc.)
            template_name = rules.get("templateName")
            if template_name:
                try:
                    loc = page.locator(self.REFSIX_SELECTORS["form_template"]).first
                    if await loc.count() > 0:
                        await loc.select_option(label=template_name)
                except Exception:
                    pass
                await asyncio.sleep(300 / 1000)

            # Team Size
            team_size = rules.get("teamSize")
            if team_size is not None:
                await self._try_click_or_fill(page, self.REFSIX_SELECTORS["setup_team_size"], str(int(team_size)), "fill")

            # Bench Size (subsNo)
            subs_no = rules.get("subsNo") if "subsNo" in rules else rules.get("benchSize")
            if subs_no is not None:
                await self._try_click_or_fill(page, self.REFSIX_SELECTORS["setup_subs_size"], str(int(subs_no)), "fill")

            # Number of periods (1, 2, 3, or 4)
            periods_no = rules.get("periodsNo")
            if periods_no is not None:
                val = str(int(periods_no))
                sel = self.REFSIX_SELECTORS["setup_periods_no"]
                for s in [x.strip() for x in sel.split(",")]:
                    try:
                        loc = page.locator(s).first
                        if await loc.count() > 0:
                            await loc.select_option(value=val)
                            break
                    except Exception:
                        continue
                await asyncio.sleep(200 / 1000)

            # Period timings (timingsperiod1, timingsperiod2, ...)
            period_lengths = rules.get("periodLengths")
            if period_lengths is None and rules.get("gameGrossTime") is not None and rules.get("periodsNo") is not None:
                pn = int(rules["periodsNo"])
                if pn > 0:
                    total = int(rules["gameGrossTime"])
                    period_lengths = [total // pn] * pn
            if period_lengths:
                period_inputs = await page.locator(self.REFSIX_SELECTORS["setup_timing_period"]).all()
                for i, length in enumerate(period_lengths[: len(period_inputs)]):
                    await period_inputs[i].fill(str(int(length)))
                await asyncio.sleep(150 / 1000)

            # Interval timings (timingsinterval1, timingsinterval2, ...)
            interval_lengths = rules.get("intervalLengths")
            if interval_lengths is None:
                interval_lengths = [rules.get("interval1"), rules.get("interval2")]
                interval_lengths = [x for x in interval_lengths if x is not None]
            if interval_lengths:
                interval_inputs = await page.locator(self.REFSIX_SELECTORS["setup_timing_interval"]).all()
                for i, length in enumerate(interval_lengths[: len(interval_inputs)]):
                    await interval_inputs[i].fill(str(int(length)))
                await asyncio.sleep(150 / 1000)

            # Extra time (Yes/No)
            et = rules.get("extraTimeAvailable")
            if et is not None:
                label = "Yes" if et else "No"
                try:
                    loc = page.locator(self.REFSIX_SELECTORS["setup_extra_time"]).first
                    if await loc.count() > 0:
                        await loc.select_option(label=label)
                    if label == "Yes":
                        half_length = rules.get("extraTimeHalfLength")
                        if half_length is not None:
                            et_half_length_locator = page.locator(self.REFSIX_SELECTORS["setup_extra_time_half_length"]).first
                            await et_half_length_locator.fill(str(int(half_length)))
                except Exception:
                    pass

            # Penalties (Yes/No)
            pens = rules.get("penaltiesAvailable")
            if pens is not None:
                label = "Yes" if pens else "No"
                try:
                    loc = page.locator(self.REFSIX_SELECTORS["setup_penalties"]).first
                    if await loc.count() > 0:
                        await loc.select_option(label=label)
                except Exception:
                    pass

            # Record goal scorers (Yes/No)
            goal_scorers = rules.get("withGoalScorers")
            if goal_scorers is not None:
                label = "Yes" if goal_scorers else "No"
                try:
                    loc = page.locator(self.REFSIX_SELECTORS["setup_goal_scorers"]).first
                    if await loc.count() > 0:
                        await loc.select_option(label=label)
                except Exception:
                    pass

            # Temporary dismissals (None / System A / System B)
            sin_bin = rules.get("sinBinSystem")
            if sin_bin is not None:
                label_map = {"none": "None", "systemA": "System A (all yellows)", "systemB": "System B (predefined yellows)"}
                label = label_map.get(str(sin_bin).lower(), str(sin_bin))
                try:
                    loc = page.locator(self.REFSIX_SELECTORS["setup_sin_bin"]).first
                    if await loc.count() > 0:
                        await loc.select_option(label=label)
                except Exception:
                    pass

            # Misconduct codes (by value or label, e.g. "custom", "fifa")
            misconduct = rules.get("misconductCodeId")
            if misconduct:
                try:
                    loc = page.locator(self.REFSIX_SELECTORS["setup_misconduct_code"]).first
                    if await loc.count() > 0:
                        await loc.select_option(value=str(misconduct))
                except Exception:
                    try:
                        await loc.select_option(label=str(misconduct))
                    except Exception:
                        pass

            return True
        except Exception as e:
            self.logger.error(f"RefSix fill_match_setup error: {e}")
            return False

    async def create_game_in_refsix(
        self,
        username: str,
        password: str,
        game: dict,
        page: Page = None,
        timeout_ms: Optional[int] = None,
        navigation_timeout_ms: Optional[int] = None,
        action_timeout_ms: Optional[int] = None,
    ) -> dict:
        """
        Open a browser, go to https://my.refsix.com/, log in, open Fixtures, and create a new match from `game`.

        Args:
            username: RefSix login username/email.
            password: RefSix login password.
            game: Game object (refPortal style). Expected keys (any subset):
                - gameTitle or homeTeam, guestTeam
                - date / gameDate (datetime or string YYYY-MM-DD)
                - gameTime (time or string HH:MM)
                - fieldName / venue / field
                - tournamentName / tournament
            logger: Logger instance (e.g. self.logger).
            headless: If False, browser window is visible.
            timeout_ms: Deprecated alias for action_timeout_ms (kept for callers). Prefer action_timeout_ms.
            navigation_timeout_ms: Max time for page.goto / navigations (default REFSIX_NAV_TIMEOUT_MS or 120000).
            action_timeout_ms: Default for clicks/fills/locators (default REFSIX_ACTION_TIMEOUT_MS or 30000).

        Returns:
            dict with keys: success (bool), message (str), details (dict e.g. url, error).
        """
        result = {"success": False, "message": "", "details": {}}
        game_flat = self.normalizeGameForRefsix(game)

        nav_timeout = navigation_timeout_ms
        if nav_timeout is None:
            nav_timeout = int(os.getenv("REFSIX_NAV_TIMEOUT_MS", "120000"))
        if action_timeout_ms is not None:
            act_timeout = action_timeout_ms
        elif timeout_ms is not None:
            act_timeout = timeout_ms
        else:
            act_timeout = int(os.getenv("REFSIX_ACTION_TIMEOUT_MS", "30000"))

        try:
            # 1. Go to RefSix
            await page.goto(
                self.REFSIX_FIXTURES_URL,
                wait_until=_REFSIX_GOTO_WAIT,
                timeout=nav_timeout,
            )
            await asyncio.sleep(400 / 1000)
            if page.url != self.REFSIX_FIXTURES_URL:
                await page.goto(
                    self.REFSIX_BASE_URL,
                    wait_until=_REFSIX_GOTO_WAIT,
                    timeout=nav_timeout,
                )
                result["details"]["url"] = page.url
                await asyncio.sleep(200 / 1000)

                # 2. Login
                if not await self._login_refsix(page, username, password):
                    result["message"] = "RefSix login failed (check selectors or credentials)."
                    result["details"]["step"] = "login"
                    return result

                await page.goto(
                    self.REFSIX_FIXTURES_URL,
                    wait_until=_REFSIX_GOTO_WAIT,
                    timeout=nav_timeout,
                )
                await asyncio.sleep(400 / 1000)

            # 3. Fixtures -> New Match
            if not await self._open_fixtures_and_click_new_match(page, navigation_timeout_ms=nav_timeout):
                await helpers.takeScreenshot(tag='refsix')
                result["message"] = "RefSix: could not open Fixtures or New Match."
                result["details"]["step"] = "fixtures"
                return result

            # 4. Fill form and submit
            if not await self._fill_new_match_form(page, game_flat):
                await helpers.takeScreenshot(tag='refsix')
                result["message"] = "RefSix: could not fill or submit new match form."
                result["details"]["step"] = "form"
                return result

            result["success"] = True
            result["message"] = "Match creation flow completed. Verify on RefSix."
            result["details"]["step"] = "submit"
            result["details"]["game_flat"] = game_flat

        except Exception as e:
            self.logger.error(f"RefSix create_game_in_refsix error: {e}")
            result["message"] = str(e)
            result["details"]["error"] = str(e)
        finally:
            if page:
                await page.close()

        return result

if __name__ == "__main__":
    from shared.appContainer import AppContainer
    container = AppContainer.getAppContainer()
    cacheService:CacheService = container.cache_service()
    logger:Logger = container.logger()
    refsix_client = RefSixClient(logger, cacheService)
    username = "שׁשׁשׁשׁ"
    password = "ששששששש"
    from shared.handleRefereeData import HandleRefereeData
    handleRefereeData:HandleRefereeData = container.handle_referee_data()
    refereeGames = handleRefereeData.getRefereeGames(tenantKey=['IL#football#2025-26'], mobileNo='+972547799979', from_date=helpers.localNow() - timedelta(days=1), to_date=helpers.localNow()+timedelta(days=2))
    for refereeGame in refereeGames.values():
        gameDetail = cacheService.getGameDetail(game=refereeGame)
        result = asyncio.run(refsix_client.create_game_in_refsix(username=username, password=password, game=gameDetail, headless=False))
        print(result)