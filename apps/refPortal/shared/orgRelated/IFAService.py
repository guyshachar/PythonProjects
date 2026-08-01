from datetime import datetime, timedelta
import os
import sys
from pathlib import Path
import asyncio
import re
#from dependency_injector import containers, providers
from urllib.parse import urlencode, urlparse, parse_qs
from bs4 import BeautifulSoup
import html2text
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.handleUsers import HandleUsers
from shared.logger import Logger
# MessagingService imported via TYPE_CHECKING in orgServiceBase to avoid circular import
from shared.db import CacheService
from shared.orgRelated.orgServiceBase import OrgServiceBase, OrgServiceCountryCode, OrgServiceEventType
from shared.orgRelated.multiTenantSupport import MultiTenantSupport
from shared.orgRelated.ifa_payment_scraper import IfaPaymentScraper

class IFAService(OrgServiceBase):
    def __init__(self, logger:Logger, multiTenantSupport:MultiTenantSupport, cacheService:CacheService, handleUsers:HandleUsers, messagingService:'MessagingService', tenantRepository=None):
        super().__init__(logger=logger, multiTenantSupport=multiTenantSupport, cacheService=cacheService, handleUsers=handleUsers, messagingService=messagingService, countryCode=OrgServiceCountryCode.ISRAEL, eventType=OrgServiceEventType.IFA, tenantRepository=tenantRepository)

        self.protocol = 'https://'
        self.baseUrl = 'www.football.org.il'
        self.baseVoleUrl = 'vole.one.co.il'
        self.translation_table = str.maketrans('', '', "!@#'? \"")

        self.loginUrl = os.getenv('loginUrl') or 'https://ref.football.org.il/login'
        self.gamesUrl = os.getenv('gamesUrl') or 'https://ref.football.org.il/referee/home'
        self.gameReportsUrl = os.getenv('gameReportsUrl') or 'https://ref.football.org.il/referee/game-reports'
        self.reviewsUrl = os.getenv('reviewsUrl') or 'https://ref.football.org.il/referee/reviews'
        self.paymentsUrl = os.getenv('paymentsUrl') or 'https://ref.football.org.il/referee/payments'

        self.ifaPaymentScraper = IfaPaymentScraper(logger=self.logger)
        from shared.refsix_client import RefSixClient
        self.refsixClient = RefSixClient(self.logger, self.cacheService)

        self.gameReportFieldMap = {
            'startTime': "[formcontrolname='start']",
            'endTime': "[formcontrolname='end']",
            'breakMinutes': "[formcontrolname='brakeTime']",
            'addedTimeMinutes': "[formcontrolname='duration']",
            'addedTimeReason': "[formcontrolname='reason']",
            'homeScore': "div.input:has(i.home-team) input",  # no formcontrolname on this input
            'guestScore': "[formcontrolname='guestTeam']",
            # Half-time score row only appears for league/cup games (confirmed via a submitted
            # report showing 'מחצית: 1-0'), not the training-game form used to verify the rest
            # of this map. Scoped by the row's visible label since the final-score row's inputs
            # aren't reliably distinguishable by formcontrolname alone (see homeScore above) —
            # verify against a live pending league report and adjust if this doesn't match.
            'homeHTScore': "div.score-row:has-text('מחצית') div.input:has(i.home-team) input",
            'guestHTScore': "div.score-row:has-text('מחצית') [formcontrolname='guestTeam']",
        }

        self.dataDic1 = {
            "games" : {
                "סטטוסTag": { "name": "סטטוס", "dic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")] },
                "* שםTag": { "name": "* סטטוס", "dic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")] },
           },
            "gamesReports" : {
                "סטטוסTag": { "name": "סטטוס", "dic": [("new_report.svg", "מחכה לעדכון"), ("in_process.svg", "בעדכון")] },
           },
            "reviews": {
            }
        }

        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "convert": self.convertGamesTableToText,
                "parse": self.parseText,
                "tags" : [ 'תאריך', "יום", "מסגרת משחקים", "משחק", "סבב", "מחזור", "מגרש", "סטטוס" ],
                "initTag" : 'תאריך',
                "refereesTags": [ "תפקיד", "* שם", "* סטטוס", "* דרג", "* טלפון", "* כתובת" ],
                "pkrefereesTags": "תפקיד",
                "initrefereesTag" : 'תפקיד',
                "סטטוסTag": { "name": "סטטוס", "dic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")] },
                "* שםTag": { "name": "* סטטוס", "dic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")] },
                'removeFilter': 'תאריך',
                'pkTags': [ "tournamentName", "gameTitle", "fixture" ],
            },
            "gamesReports" : {
                "parse": self.parseText,
                "tags" : [ 'תאריך', "מסגרת משחקים", "מח.", "מגרש", "סטטוס", "קבוצה ביתית קבוצה אורחת" ],
                "initTag" : 'תאריך',
                "סטטוסTag": { "name": "סטטוס", "dic": [("new_report.svg", "מחכה לעדכון"), ("new_report2.svg", " בעדכון")] },
                "pkTags": [ "tournamentName", "gameTitle", "fixture" ],
                "url": "https://ref.football.org.il/referee/home",
                "convert": self.convertGamesTableToText,
            },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "convert": self.convertReviewsTableToText,
                "parse": self.parseText,
                "tags" : [ "מס.", 'תאריך', "שעה", "מסגרת משחקים", "משחק", "מגרש", "מחזור", "תפקיד במגרש", "מבקר", "ציון" ],
                "initTag" : "מס.",
                "excludeCompareTags" : [ "מס." ],
                "pkTags": [ "tournamentName", "gameTitle", "fixture" ],
            }
        }

    async def get2FA_PortalCode(self, tenantKey, mobileNo, _2FA_PortalCodeField):
        now = helpers.localNow()
        _2FA_PortalCodeObj = self.cacheService.getCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='2FA_PortalCode')
        if _2FA_PortalCodeObj:
            if not isinstance(_2FA_PortalCodeObj, dict):
                await _2FA_PortalCodeField.fill(_2FA_PortalCodeObj)
                await _2FA_PortalCodeField.press("Enter")
                #await page.wait_for_load_state('networkidle', timeout=3000)
                await asyncio.sleep(1000 * 2 * self.latencyFactor / 1000)
                return True

            _2FA_PortalCode = _2FA_PortalCodeObj.get('2FA_PortalCode')
            _2FA_PortalCodeDatetime = _2FA_PortalCodeObj.get('2FA_PortalCodeDatetime')
            timeElapsed = now - _2FA_PortalCodeDatetime
            if _2FA_PortalCode:
                if timeElapsed < timedelta(seconds=15 * self.latencyFactor):
                    await _2FA_PortalCodeField.fill(_2FA_PortalCode)
                    await _2FA_PortalCodeField.press("Enter")
                    #await page.wait_for_load_state('networkidle', timeout=3000)
                    await asyncio.sleep(1000 * 2 * self.latencyFactor / 1000)

                else:
                    refereeDetail = self.globalRefereesByMobile[mobileNo]
                    self.logger.warning(f'2FA Portal Code expired, mobileNo={mobileNo}', refereeDetail=refereeDetail)
            return True
        
        return False

    async def login(self, refereeDetail, page) -> tuple[bool, str]:
        try:
            self.logger.info(f'login start')
            tenantKey = refereeDetail['tenantKey']
            id_number = refereeDetail.get('idNumber')
            mobileNo = refereeDetail['mobileNo']
            self.logger.info(f'login#1, tenantKey={tenantKey}, id_number={id_number}, mobileNo={mobileNo}')
            loginOnHold = self.cacheService.getCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='loginOnHold')
            
            try:
                pageOk = page.url if page else 'NotOk'
                self.logger.info(f'login#2, pageOk={pageOk}')
            except Exception as ex:
                self.logger.error(f'login#2, error={ex}')
                pageOk = 'pageError'
            
            self.logger.info(f'login#3, pageOk={pageOk}')
            now = helpers.localNow()
            self.logger.info(f'login#4, loginOnHold={loginOnHold} skipLoginOnHold={os.getenv('skipLoginOnHold', 'False') == 'True'}')
            if loginOnHold and not os.getenv('skipLoginOnHold', 'False') == 'True':
                return False, f'Login on hold'#, nextLoginAttempt in {round(timeToNextLoginAttempt.total_seconds()/60)} minutes'
            self.logger.info(f'login#5, loginOnHold={loginOnHold}')
            self.logger.info(f'login#6, page.url={page.url} page={page is not None}')
            message = 'failed'
            t=0
            self.logger.info(f'login#5, t={t}, page.url={page.url}')
            while page.url != self.gamesUrl and t < 2:
                t+=1
                self.logger.debug(f'login#{t}', refereeDetail=refereeDetail)
                try:
                    self.logger.info(f'login#{t}, url={self.loginUrl}')
                    page = await self.gotoUrl(page=page, url=self.loginUrl, refereeDetail=refereeDetail)
                    await asyncio.sleep(1500*t * self.latencyFactor / 1000)
                    #await self.takeScreenshot(page, refereeDetail, 'login')
                    #await helpers.takeScreenshot(page=page, tag='login', refereeDetail=refereeDetail)
                    input_elements = await page.query_selector_all('input')
                    input_elements_cnt = len(input_elements)
                    self.logger.info(f'login#{t}, input_elements_cnt={input_elements_cnt}')
                    if input_elements_cnt != 2:
                        self.logger.warning(f'Login form changed#{t}, RefId={refereeDetail["refId"]}', refereeDetail=refereeDetail)
                        return False, f'Login form changed, input_elements_cnt={input_elements_cnt}'
      
                    usernameField = input_elements[0]
                    await usernameField.fill(id_number)

                    idField = input_elements[1]
                    await idField.fill(mobileNo)

                    await idField.press("Enter")
                    self.cacheService.setCacheOnlyKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='2FA_PortalCode_RequestDatetime', value=helpers.localNow(), ttlSeconds=60 * 30)
                    await asyncio.sleep(5000 * self.latencyFactor / 1000)

                    # 2FA Portal Code
                    input_elements = await page.query_selector_all('input')
                    input_elements_cnt = len(input_elements)
                    if input_elements_cnt != 1:
                        self.logger.warning(f'Login form changed#{t}, mobileNo={mobileNo}', refereeDetail=refereeDetail)
                        return False, f'Login form changed, input_elements_cnt={input_elements_cnt}'

                    result = await helpers.retryBlock(self.get2FA_PortalCode, tenantKey=tenantKey, mobileNo=mobileNo, _2FA_PortalCodeField=input_elements[0])
                    if result:
                        if page.url != self.gamesUrl and t == 0:
                            self.logger.warning(f'2FA Portal Code expired, waiting for 25 seconds, mobileNo={mobileNo}', refereeDetail=refereeDetail)
                            await asyncio.sleep(25000 / 1000)
                    else:
                        break
                    
                except Exception as ex:
                    self.logger.error('login', ex, refereeDetail=refereeDetail)
            
            await asyncio.sleep(200 * self.latencyFactor / 1000)

            if page.url != self.gamesUrl:
                self.logger.warning(f'Login failed#{t}, RefId={refereeDetail["refId"]}', refereeDetail=refereeDetail)
            else:
                self.logger.debug(f'Login successfull#{t}', refereeDetail=refereeDetail)
                return True, 'Login successful'

        except Exception as ex:
            self.logger.error(f'Login', ex, takeScreenshot=True, refereeDetail=refereeDetail)
            message = str(ex)

        await helpers.takeScreenshot(tag='login')
        
        return False, message
    
    async def logout(self, refereeDetail, page):
        t=0
        
        while page.url != self.loginUrl and t < 3:
            try:
                t+=1
                page = await self.gotoUrl(page=page, url=self.loginUrl, refereeDetail=refereeDetail)
                self.logger.debug(f'logout#{t}', refereeDetail=refereeDetail)
                button_elements = await page.query_selector_all("button")
                logoutButtons = [button for button in button_elements if (await button.inner_text()).strip() == "יציאה"]

                self.logger.debug(f'logoutButtons={len(logoutButtons)}')
                if len(logoutButtons) == 1:
                    logoutButton = button_elements[0]
                    await logoutButton.click()
                await asyncio.sleep(1000*t * self.latencyFactor / 1000)
            except Exception as ex:
                pass

        if page.url != self.loginUrl:
            self.logger.error(f'Logout failed#{t}', None, refereeDetail=refereeDetail)
            return False
        else:
            self.logger.debug(f'Logout successfull#{t}', refereeDetail=refereeDetail)
    
        return True

    async def changePassword(self, refereeDetail, targetRefereeDetail, page) -> tuple[bool, str]:
        return False, 'not implemented'

    def setFetchDates(self, refereeData):
        now = datetime.now().date()
        if 'games' not in refereeData:
            refereeData['games'] = {}
        refereeData['games']['fromDate'] = now - timedelta(days=2)
        refereeData['games']['toDate'] = now + timedelta(days=365)
        if 'reviews' not in refereeData:
            refereeData['reviews'] = {}
        refereeData['reviews']['fromDate'] = None
        refereeData['reviews']['toDate'] = None

    async def collectItemsForAssigner(self, tenantKey, objType, refereeData, page):
        pass

    async def parseListForReferee(self, tenantKey, objType, refereeData, page):
        try:
            mobileNo = refereeData['mobileNo']
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            parsedList = None
            gamesReports = None

            if objType == 'gamesReports':
                reportsResult = await self.convertGamesReportsTableToText(page=page, refereeDetail=refereeDetail)
                gamesReports = await self.dataDic[objType]['parse'](tenantKey=tenantKey, objType=objType, convertResults=reportsResult)
                for gamePk, gameReport in gamesReports.items():
                    gameDetail = self.cacheService.get_tournament_game_by_pk(tenantKey=tenantKey, tournamentName=gameReport.get('tournamentName'), gamePk=gamePk)
                    if gameDetail and gameDetail.get('internalGameId'):
                        gameReport['internalGameId'] = gameDetail.get('internalGameId')
                        continue
                    dateTextCell = gameReport.get('cells', {}).get('dateText')
                    if dateTextCell:
                        try:
                            await dateTextCell.click()
                            await asyncio.sleep(1000 / 1000)
                            if 'game-reports' in page.url:
                                gameReport['gameReportUrl'] = page.url
                                parsed_url = urlparse(page.url)
                                path_parts = parsed_url.path.strip('/').split('/')
                                game_reports_index = path_parts.index('game-reports')
                                if game_reports_index + 1 < len(path_parts):
                                    game_id = path_parts[game_reports_index + 1]
                                    gameReport['internalGameId'] = game_id
                                await page.go_back()
                                await asyncio.sleep(200 / 1000)
                            else:
                                closeButton = await page.query_selector("button.btn.border.close")
                                if closeButton:
                                    await closeButton.click()
                                    await asyncio.sleep(200 / 1000)
                        except Exception as ex:
                            pass
                return gamesReports

            page = await self.gotoUrl(page, self.dataDic[objType]['url'])
            await asyncio.sleep(300 / 1000)
            title = await page.title()
            self.logger.debug(f'title: {title}', refereeDetail=refereeDetail)
            
            convertResults = await self.dataDic[objType]['convert'](page, refereeDetail)
            self.logger.debug(f'convertResults: {convertResults}', refereeDetail=refereeDetail)

            #if objType == 'gamesReports':
            #    return gamesReports

            if convertResults != None and self.dataDic[objType].get('parse'):
                parsedList = await self.dataDic[objType]['parse'](tenantKey=tenantKey, objType=objType, convertResults=convertResults)
                self.logger.debug(f'parsedList: {parsedList}', refereeDetail=refereeDetail)

            return parsedList
        except Exception as ex:
            self.logger.error('parseListForReferee', ex, refereeDetail=refereeDetail)
            return None
    
    async def convertGamesTableToText(self, page, refereeDetail):
        games = 'games'
        gamesResults = []

        try:
            gamesTable = await page.locator("app-home-assignment-confirmation table").all()
            if not gamesTable:
                gamesTable = await page.get_by_role("heading", name="םיצוביש רושיא").locator("xpath=following-sibling::table[1]").all()

            #gamesTable = await self.getLocator(parent=page, selector='table.ng-tns-c150-1')
            self.logger.debug(f'convertGamesTableToText/tablesLocator={1 if gamesTable else 0}', refereeDetail=refereeDetail)
            if not gamesTable or len(gamesTable) == 0: #probably no games
                return []
            
            if len(gamesTable) > 0: 
                gamesTable = gamesTable[0]
                gameRows = await gamesTable.locator('tr').all()
                rowsCnt = len(gameRows)
                self.logger.debug(f'convertGamesTableToText/rowsLocator={rowsCnt}', refereeDetail=refereeDetail)
                if rowsCnt == 1:
                    self.logger.warning(f'Fail to read games data', refereeDetail=refereeDetail)
                    return None

                gameHeaders = await gameRows[0].locator('th').all()
                gameHeadersTexts = [(await header.inner_text()).strip() for header in gameHeaders]

                i = 0
                for gameRow in gameRows[1:]:  # Skip the header row
                    i += 1
                    gameCells = await gameRow.locator('td').all()
                    if len(gameCells) == len(gameHeadersTexts):  # Regular rows
                        for cellIndex, (gameHeader, gameCell) in enumerate(zip(gameHeadersTexts, gameCells)):
                            cellText = (await gameCell.inner_text()).strip()
                            cellHTml = await gameCell.evaluate("element => element.outerHTML")
                            (tagName, tagText) = self.getTagText(games, gameHeader, cellHTml)
                            obj = None

                            # Assign unique ID to the cell
                            # Best practice: Use setAttribute for HTML attributes (more standard than direct property assignment)
                            #cellId = f'gm_{gameHeader}_{i}'
                            #await gameCell.evaluate('(element, unique_id) => element.setAttribute("id", unique_id)', cellId)
                            
                            # Store selector string instead of locator to avoid stale element issues
                            # Option 1: Use the ID selector (most reliable since we assign it)
                            #cellSelector = f'#{cellId}'
                            # Option 2: Store row index and cell index for reconstruction
                            # cellSelector = f'tr:nth-child({i+2}) td:nth-child({cellIndex+1})'  # +2 because we skip header, +1 for 1-based nth-child

                            if gameHeader and (cellText or tagText):
                                obj = {'header': gameHeader, 'text': cellText or tagText, 'cellSelector': gameCell, 'rowIndex': i, 'cellIndex': cellIndex}
                                gamesResults.append(obj)
                            if tagName and cellText and tagText:
                                obj = {'header': tagName, 'text': tagText, 'cellSelector': gameCell, 'rowIndex': i, 'cellIndex': cellIndex}
                                gamesResults.append(obj)

                    elif len(gameCells) == 1:  # Row with colspan
                        cellHTml = await gameCells[0].evaluate("element => element.outerHTML")
                        transformedHtml = self.transformHtmlTable(cellHTml)
                        #self.logger.warning(str(html1))
                        nestedResult = await self.convertGamesTableToTextUsingSoup(transformedHtml)
                        gamesResults.append({'text': ''})
                        for obj in nestedResult:
                            gamesResults.append(obj)
                
        except Exception as ex:
            self.logger.error('convertGamesTableToText', ex, refereeDetail=refereeDetail)
            return None
        
        return gamesResults

    async def convertGamesTableToTextUsingSoup(self, html):
        games = "games"
        results = []

        try:
            if html == None:
                return results

            # Parse the HTML using BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            h = html2text.HTML2Text()
            # Ignore converting links from HTML
            h.ignore_links = False

            # Extract table rows
            rows = soup.find_all('tr')  
            
            # Get headers (assumes the first row contains headers)
            headers = [th.get_text(strip=True) for th in rows[0].find_all('th')]
            if len(rows) <= 1:
                pass
            else:
                i = 0
                for row in rows[1:]:  # Skip the header row
                    i += 1
                    cells = row.find_all('td')
                    if len(cells) == len(headers):  # Regular rows
                        for header, cell in zip(headers, cells):
                            cellText = cell.get_text(strip=True)
                            (tagName, tagText) = self.getTagText(games, header, str(cell))
                            obj = None
                            if header and (cellText or tagText):
                                obj = {'header': header, 'text': cellText or tagText, 'cell': cell}
                                results.append(obj)
                            if tagName and cellText and tagText:
                                obj = {'header': tagName, 'text': tagText, 'cell': cell}
                                results.append(obj)

        except Exception as ex:
            self.logger.error('convertGamesTableToTextUsingSoup', ex)
            return None

        return results

    async def convertGamesReportsTableToText(self, page, refereeDetail):
        gamesReports = 'gamesReports'
        results = []

        try:
            gamesTables = await page.locator("app-home-unfinished-game-reports mat-accordion").all()
            rows = await page.locator("app-home-unfinished-game-reports mat-expansion-panel").all()
            #if not gamesTables:
            #    gamesTables = page.get_by_role("heading", name="אל וא וטלקנ אל םרובע תוחוד רשא םיקחשמ locator("xpath=following-sibling::mat-accordion[1]").)"ומלשוה
            #gamesTables = await page.locator('table.ng-tns-c150-1').all()
            gamesReportsTables = await page.locator('table.ng-star-inserted').all()
            gamesReportsTablesCnt = len(gamesReportsTables)
            self.logger.debug(f'convertGamesReportsTableToText/tablesLocator={gamesReportsTablesCnt}', refereeDetail=refereeDetail)
            if gamesReportsTablesCnt == 0: #probably no games
                return []
            
            if gamesReportsTablesCnt == 2 if len(gamesTables) > 0 else 1: 
                gamesReportTable = gamesReportsTables[gamesReportsTablesCnt-1]
                gameReportsRows = await gamesReportTable.locator('tr').all()
                rowsCnt = len(gameReportsRows)
                self.logger.debug(f'convertGamesReportsTableToText/rowsLocator={rowsCnt}', refereeDetail=refereeDetail)
                if rowsCnt == 0:
                    self.logger.warning(f'Fail to read games report data', refereeDetail=refereeDetail)
                    return None

                if rowsCnt == 1:
                    return []

                gameReportsHeaders = await gameReportsRows[0].locator('th').all()
                gameReportsHeadersTexts = [(await header.inner_text()).strip().replace(':', '') for header in gameReportsHeaders]

                i = 0
                for gameReportRow in gameReportsRows[1:]:  # Skip the header row
                    i += 1
                    gameReportCells = await gameReportRow.locator('td').all()
                    if len(gameReportCells) == len(gameReportsHeadersTexts):  # Regular rows
                        for gameHeader, gameReportCell in zip(gameReportsHeadersTexts, gameReportCells):
                            cellText = (await gameReportCell.inner_text()).strip()
                            cellHTml = await gameReportCell.evaluate("element => element.outerHTML")
                            (tagName, tagText) = self.getTagText(gamesReports, gameHeader, cellHTml)
                            obj = None

                            if gameHeader and (cellText or tagText):
                                obj = {'header': gameHeader, 'text': cellText or tagText, 'cell': gameReportCell}
                                results.append(obj)
                            if tagName and cellText and tagText:
                                obj = {'header': tagName, 'text': tagText, 'cell': gameReportCell}
                                results.append(obj)
                                        
        except Exception as ex:
            self.logger.error('convertGamesReportsTableToText', ex, refereeDetail=refereeDetail)
            return None
        
        return results

    async def convertReviewsTableToText(self, page, refereeDetail):
        reviews = 'reviews'
        results = []

        try:
            reviewsTable = await self.getLocator(parent=page, selector='table.ng-star-inserted')
            self.logger.debug(f'convertReviewsTableToText/tablesLocator={reviewsTable}', refereeDetail=refereeDetail)
            if not reviewsTable: #Still need to investigate this scenario
                await helpers.startTracing(page)
                await asyncio.sleep(500 / 1000)
                await helpers.stopTracing(page, f'refId{refereeDetail["refId"]}-NoReviews')
                return None
            
            reviewRows = await reviewsTable.locator('tr').all()
            rowsCnt = len(reviewRows)
            self.logger.debug(f'convertReviewsTableToText/rowsLocator={rowsCnt}', refereeDetail=refereeDetail)
            if rowsCnt <= 1:
                return None
            
            reviewHeaders = await reviewRows[0].locator('th').all()
            reviewHeadersTexts = [(await header.inner_text()).strip() for header in reviewHeaders]
            # Process each subsequent row and map to headers
            i = 0
            for reviewRow in reviewRows[1:]:  # Skip the header row
                i += 1
                reviewCells = await reviewRow.locator('td').all()
                if len(reviewCells) == len(reviewHeadersTexts):  # Regular rows
                    for reviewHeader, reviewCell in zip(reviewHeadersTexts, reviewCells):
                        cellText = (await reviewCell.inner_text()).strip()
                        cellHTml = await reviewCell.evaluate("element => element.outerHTML")
                        (tagName, tagText) = self.getTagText(reviews, reviewHeader, cellHTml)
                        obj = None

                        #await reviewCell.evaluate('(element, unique_id) => element.setAttribute("id", unique_id)', f'{reviewHeader}_{i}')

                        if reviewHeader and (cellText or tagText):
                            obj = {'header': reviewHeader, 'text': cellText or tagText, 'cell': reviewCell}
                            results.append(obj)
                        if tagName and cellText and tagText:
                            obj = {'header': tagName, 'text': tagText, 'cell': reviewCell}
                            results.append(obj)

                elif len(reviewCells) == 1:  # Row with colspan
                    results.append({'text': await reviewCells.nth(0).inner_text()})
                
        except Exception as ex:
            self.logger.error(f'convertReviewsTableToText', ex, refereeDetail=refereeDetail)
            return None
        
        return results

    async def parseText(self, tenantKey, objType, convertResults):
        try:
            data = self.dataDic[objType]
            listObjects = []
            obj = None
            refereesList = []
            refereesObj = {}
            refereesCells = {}

            if convertResults:
                for convertResult in convertResults:
                    header = convertResult.get("header")
                    # Get cell selector instead of locator to avoid stale element issues
                    cellSelector = convertResult.get('cellSelector')  # New: selector string
                    cell = convertResult.get('cell')  # Old: locator (for backward compatibility)
                    line = f'{header+":" if header else ""}{convertResult["text"]}'
                    line = line.strip()
                    if line:
                        idx = line.find(':')
                        if idx > -1:
                            self.logger.debug(f'{idx} {len(line)} {line}')
                            tag = line[:idx].strip()
                            tag = header
                            tagValue = line[idx+1:].strip()
                            if tag in data["tags"]:
                                if tag == data["initTag"]:
                                    if obj:
                                        if refereesObj:
                                            refereesPk = refereesObj[data['pkrefereesTags']]
                                            refereesList.append(refereesObj)
                                            '''
                                            if refereesList.get(refereesPk):
                                                refereesList[f'{refereesPk}*'] = refereesObj    
                                            else:
                                                refereesList[refereesPk] = refereesObj
                                            '''
                                        obj['referees'] = refereesList
                                        obj['cells'] = refereesCells  # Store selectors (strings) instead of locators
                                        # Note: When using cells later, recreate locator from selector using page.locator(selector)
                                        obj['state'] = 'active'
                                        refereesList = []
                                        refereesObj = {}
                                        refereesCells = {}
                                        listObjects.append(obj)
                                    obj = {}
                                obj[tag] = tagValue
                                # Store selector string instead of locator
                                refereesCells[header] = cellSelector if cellSelector else cell
                            elif tag in data.get("refereesTags", []):
                                if tag == data["initrefereesTag"]:
                                    if refereesObj:
                                        refereesPk = refereesObj[data['pkrefereesTags']]
                                        refereesList.append(refereesObj)
                                        '''
                                        if refereesList.get(refereesPk):
                                            refereesList[f'{refereesPk}*'] = refereesObj    
                                        else:
                                            refereesList[refereesPk] = refereesObj
                                        '''
                                    refereesObj = {}
                                refereesObj[tag] = tagValue
                                # Store selector string instead of locator
                                refereesCells[header] = cellSelector if cellSelector else cell

                if refereesObj:
                    refereesPk = refereesObj[data['pkrefereesTags']]
                    refereesList.append(refereesObj)
                    '''
                    if refereesList.get(refereesPk):
                        refereesList[f'{refereesPk}*'] = refereesObj    
                    else:
                        refereesList[refereesPk] = refereesObj
                    '''
                if obj:
                    obj['referees'] = refereesList
                    obj['cells'] = refereesCells
                    listObjects.append(obj)

            dicObjects = {}
            for obj in listObjects:
                obj = self.multiTenantSupport.mapItem(tenantKey=tenantKey, objType=objType, obj=obj)
                pk = self.getPk(objType=objType, obj=obj)
                obj['gamePk'] = pk
                obj['date'] = helpers.convert_to_datetime(obj['dateText'])
                obj['state'] = 'active'
                dicObjects[pk] = obj
            self.logger.debug(f'n={len(dicObjects)} {dicObjects}')

            return dicObjects

        except Exception as ex:
            self.logger.error(f'parseText', ex)
            return None

    def getGamesUrl(self):
        return self.gamesUrl

    def getReviewsUrl(self):
        return self.reviewsUrl

    def getPk(self, objType, obj):
        data = self.dataDic[objType]
        pk = ''
        for tag in data['pkTags']:
            pk += obj[tag].replace(':', '').replace('-', '')
        return pk

    def transformHtmlTable(self, html):
        # Parse the HTML
        soup = BeautifulSoup(html, 'html.parser')

        # Create the table and header row
        table = soup.new_tag('table')
        header_row = soup.new_tag('tr')
        headers = ['תפקיד', '* שם', '* דרג', '* טלפון', '* כתובת']

        for header in headers:
            th = soup.new_tag('th')
            span = soup.new_tag('span', _ngcontent_nop_c149="", **{"class": "info"})
            span.string = header
            th.append(span)
            header_row.append(th)

        table.append(header_row)

        # Process each 'info-box'
        for info_box in soup.find_all('div', class_='info-box'):
            data_row = soup.new_tag('tr')
            # Add role (title)
            title_td = soup.new_tag('td')
            title_span = info_box.find('span', class_='title')
            title_td.append(title_span)
            data_row.append(title_td)

            # Add other fields from list items
            for li in info_box.find_all('li'):
                data_td = soup.new_tag('td')
                data_span = li.find_all('span')[-1]  # The value is in the second <span>
                data_td.append(data_span)
                data_row.append(data_td)
            
            table.append(data_row)

        # Output the transformed HTML
        return str(table.prettify())

    def getTagText(self, objType, tag, cellHtml):
        if tag and f'{tag}Tag' in self.dataDic[objType]:
            tagParse = self.dataDic[objType][f'{tag}Tag']
            for filter, useText in tagParse['dic']:
                if filter == None or filter in cellHtml:
                    return tagParse['name'], useText
        
        return None, None

    async def getCupsList(self):
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            # Open the URL
            page = await self.gotoUrl(page, f'{self.protocol}{self.baseUrl}')

            # Wait for the submenu to be visible
            submenu_locator = (await page.query_selector_all("ul.second-level-list"))[3]

            # Scan all submenu items
            cupsList = await self.scarpCupList(page, submenu_locator)

            #cupsList = helpers.load_from_json('./data/tournaments/cups.json')

            # Output the collected data
            for cup in cupsList:
                self.logger.debug(f"Text: {cup}, Link: {cupsList[cup]['href']}")

            # Close the browser
            await browser.close()

            jsonHelper.save_to_file(cupsList, './data/tournaments/cups.json')

    async def createGameInRefSix(self, page, username, password, gameDetail):
        result = await self.refsixClient.create_game_in_refsix(username=username, password=password, game=gameDetail, page=page)
        return result

    async def getLeaguesList(self):
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            # Open the URL
            page = await self.gotoUrl(page, f'{self.protocol}{self.baseUrl}')

            # Wait for the submenu to be visible
            submenu_locator = (await page.query_selector_all("ul.second-level-list"))[2]
            #submenu_locator = await page.wait_for_selector("ul.submenu")

            # Scan all submenu items
            #await scarpLeaguesList(page, submenu_locator)
            await self.scrapLeaguesData(page)

            # Output the collected data
            for leagueName, league in self.cacheService.getTournaments().items():
                self.logger.debug(f"Text: {league}, Link: {league['href']}")

            # Close the browser
            await browser.close()

    async def getLeagueName(self, page, tournamentUrl):
        if page.url != f'{self.protocol}{self.baseUrl}{tournamentUrl}':
            page = await self.gotoUrl(page, f'{self.protocol}{self.baseUrl}{tournamentUrl}')#, timeout=15000)
        tableTitle = await page.query_selector_all('span.big')
        if tableTitle and len(tableTitle) == 1: 
            return (await tableTitle[0].inner_text()).strip()
        return None

    async def getVoleTableData(self, page):
        table_data = {}
        tableTitle = await page.query_selector_all('h1')
        if tableTitle: 
            div = await page.query_selector_all("div.standings_container__Dm8WX")
            if not div:
                self.logger.debug(f"No element found with selector: {'div.standings_container__Dm8WX'}")
                return table_data

            headMapping = [
                "מעבר",
                "מיקום",
                "קבוצה",
                "משחקים",
                "ניצחונות",
                "תיקו",
                "הפסדים",
                "שערים",
                "הפרש",
                "נקודות",
            ]
            headMapping1 = {
                "מיקום": "מיקום",
                "קבוצה": "קבוצה",
                "מש׳": "משחקים",
                "נצ׳": "ניצחונות",
                "ת׳": "תיקו",
                "הפ׳": "הפסדים",
                "יחס": "שערים",
                "הפרש": "הפרש",
                "נק׳": "נקודות",
            }
            # Find all rows in the table within the div
            theadTr = await div[0].query_selector_all("thead tr th")
            tbody = await div[0].query_selector_all("tbody")
            rows = await tbody[0].query_selector_all("tr")
            for row in rows:
                elements = await row.query_selector_all("td")
                cells = {}
                i = -1
                for cell in elements:
                    i += 1
                    if i == 0:
                        continue
                    cell = elements[i]
                    head = headMapping[i]
                    '''
                    if i == 0:
                        head = 'מיקום'
                    else:
                        head = await theadTr[i-1].inner_text()
                    '''
                    obj = (await cell.inner_text()).strip()
                    if False and headMapping.get(head):
                        head = headMapping[head]
                    cells[head] = obj
                teamName = cells['קבוצה'].translate(self.translation_table)
                table_data[teamName] = cells

        return table_data

    async def getIFATableData(self, page):
        table_data = {}

        roundLocator = page.locator(f"select#ddlBoxes")
        if roundLocator and await roundLocator.count() == 1:
            self.logger.debug(f'getIFATableData roundLocator={roundLocator}')
            roundOptions = roundLocator.locator('option')
            roundOptionsTexts = [await roundOptions.nth(i).text_content() for i in range(await roundOptions.count())]
            
            '''
            for roundOptionText in roundOptionsTexts:
                self.logger.debug(f'getIFATableData roundOptionText={roundOptionText}')
                await roundLocator.select_option(label=roundOptionText, timeout=15000)
                await asyncio.sleep(100/1000)
            '''
            tableTitle = await page.query_selector_all('h2#LEAGUE_TABLE_TITLE_PLAYOFF')
            if tableTitle: 
                full_view_div = await page.query_selector_all("div.vertical-title")
                if not full_view_div:
                    self.logger.debug(f"No element found with selector: {'div.vertical-title'}")
                    return table_data

                # Find all rows in the table within the div
                rows = await full_view_div[0].query_selector_all("a.table_row")
                self.logger.debug(f'getIFATableData #teams={len(rows)}')
                for row in rows:
                    # Extract all cell data (th or td)
                    elements = await row.query_selector_all("a, div")
                    cells = {}
                    href = await row.get_attribute("href")
                    cells['href'] = href
                    query = urlparse(href).query
                    params = parse_qs(query)
                    teamId = int(params.get('team_id', 0)[0])
                    cells['teamId'] = teamId
                    for cell in elements:
                        obj = (await cell.inner_text()).strip().split('\n')
                        if obj[0] == 'שערים':
                            parts = obj[1].split('-')
                            obj[1] = f'{parts[1]} - {parts[0]}'
                        cells[obj[0]] = obj[1]
                    teamName = cells['קבוצה'].translate(self.translation_table)
                    table_data[teamName] = cells

        return table_data

    async def getVoleLeagueData(self, page, voleUrl):
        table_data = {}
        t = 0
        while table_data == {} and t < 2:
            try:
                if page.url != f'{self.protocol}{self.baseVoleUrl}{voleUrl}':
                    page = await self.gotoUrl(page=page, url=f'{self.protocol}{self.baseVoleUrl}{voleUrl}')#, timeout=15000)
                await asyncio.sleep(50/1000)
                table_data = await self.getVoleTableData(page=page)
            except Exception as e:
                pass
            finally:
                pass

            t = t + 1

        return table_data

    async def getIFALeagueData(self, page, tournamentUrl):
        table_data = {}
        t = 0
        while table_data == {} and t < 2:
            try:
                if page.url != f'{self.protocol}{self.baseUrl}{tournamentUrl}':
                    page = await self.gotoUrl(page=page, url=f'{self.protocol}{self.baseUrl}{tournamentUrl}')#, timeout=15000)
                await asyncio.sleep(50/1000)
                table_data = await self.getIFATableData(page=page)
            except Exception as e:
                pass
            finally:
                pass

            t = t + 1

        return table_data

    async def refreshLeaguesTablesByTournament(self, page, tournament, section):
        tenantKey = tournament['tenantKey']
        if tournament['tournament'] == 'cup' or not section:
            self.logger.debug(f'refreshLeaguesTablesByTournament {tournament["text"]} section: {section} skipped')
            return
        tournamentName = tournament['text']
        #print(f"league={tournament} --> {section['tableResult']}")
        leagueTable = None
        if section.table_result == 'IFA':
            leagueTable = await self.getIFALeagueData(page=page, tournamentUrl=tournament['href'])
        elif section.table_result == 'Vole':
            if tournament.get('voleHref'):
                leagueTable = await self.getVoleLeagueData(page=page, voleUrl=tournament['voleHref'])
        if leagueTable:
            if tournament.get('table'):
                del tournament['table']
            self.logger.info(f'refresh league={tournament}...')
            self.logger.debug(f'league={tournament} rows={len(leagueTable)}')
            
            self.cacheService.setLeagueTable(tenantKey=tenantKey, tournamentName=tournamentName, value=leagueTable)

            tournament['tableUpdateDatetime'] = helpers.localNow()
            self.cacheService.setTournament(tenantKey=tenantKey, tournamentName=tournamentName, value=tournament)

    async def refreshLeaguesTables(self, tenantKey, tournamentName = None) -> (bool, str):
        try:
            result = False
            message = ''
            if tournamentName:
                tournamentName = self.fixNameQuote(tournamentName)
            async with async_playwright() as p:
                proxy_cfg = OrgServiceBase._browser_proxy_config()
                browser = await OrgServiceBase.launchBrowser(
                    p=p, headless=eval(os.getenv('browserHeadless', 'True')), proxy_config=proxy_cfg
                )
                context = await OrgServiceBase.createContext(browser=browser)
                stealth = Stealth()
                await stealth.apply_stealth_async(context)
                page = await context.new_page()
                for _tournamentName, tournament in self.cacheService.getTournaments(tenantKey=tenantKey, forceReload=True).items():
                    if tournamentName and tournamentName != _tournamentName:
                        continue
                    if tournament.get('section'):
                        result = True
                        self.logger.debug(f'refreshLeaguesTables {_tournamentName}')
                        await self.refreshLeaguesTablesByTournament(page=page, tournament=tournament, section=self.tenantRepository.get_section(tenant_key=tenantKey, section_name=tournament['section']))

                await browser.close()

            if tournamentName == None:
                message = f"refreshLeaguesTables tenantKey={tenantKey} tournamentName={tournamentName} טבלאות עודכנו בהצלחה"
                await self.messagingService.sendMessage(to=self.messagingService.adminMobile, message=f"{helpers.localNow()} {message}", title='עדכון טבלאות')

            return result, message
        except Exception as ex:
            self.logger.error(f'refreshLeaguesTables error={ex}')
            if False and tournamentName == None:
                await self.messagingService.sendMessage(to=self.messagingService.adminMobile, message=f"{helpers.localNow()} {ex.message}", title='עדכון טבלאות נכשל')
            return False, str(ex)

    def _find_tournament_by_vole_name(self, tenantKey, leagueName):
        leagueName = self.fixNameQuote(leagueName.strip())
        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=leagueName)
        if tournament:
            return leagueName, tournament
        altName = leagueName.replace('טרום', 'ילדים טרום')
        if altName != leagueName:
            tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=altName)
            if tournament:
                return altName, tournament
        return None, None

    async def scrapVoleLeagues(self, page, tenantKey, tournamentName=None):
        updated_count = 0
        skipped_count = 0
        leagueRows = page.locator('a.animated')
        leagueRows = [(leagueRows.nth(i)) for i in range(await leagueRows.count())]
        for leagueRow in leagueRows:
            leagueName = (await leagueRow.inner_text()).strip()
            matchedName, league = self._find_tournament_by_vole_name(tenantKey=tenantKey, leagueName=leagueName)
            if not league:
                continue
            if tournamentName and tournamentName != matchedName:
                continue
            section = self.tenantRepository.get_section(tenant_key=tenantKey, section_name=league.get('section'))
            if not section or section.table_result != 'Vole':
                continue
            leagueVoleUrl = await leagueRow.get_attribute('href')
            if not leagueVoleUrl:
                continue
            if league.get('voleHref') == leagueVoleUrl:
                skipped_count += 1
                continue
            if league.get('table'):
                del league['table']
            league['voleHref'] = leagueVoleUrl
            self.cacheService.setTournament(tenantKey=tenantKey, tournamentName=matchedName, value=league)
            updated_count += 1
            self.logger.info(f'voleHrefUpdate {matchedName} => {leagueVoleUrl}')
        return updated_count, skipped_count

    async def voleHrefUpdate(self, tenantKey, tournamentName=None) -> tuple[bool, str]:
        try:
            if tournamentName:
                tournamentName = self.fixNameQuote(tournamentName)
            async with async_playwright() as p:
                proxy_cfg = OrgServiceBase._browser_proxy_config()
                browser = await OrgServiceBase.launchBrowser(
                    p=p, headless=eval(os.getenv('browserHeadless', 'True')), proxy_config=proxy_cfg
                )
                context = await OrgServiceBase.createContext(browser=browser)
                stealth = Stealth()
                await stealth.apply_stealth_async(context)
                page = await context.new_page()
                page = await self.gotoUrl(page=page, url=f'{self.protocol}{self.baseVoleUrl}/')
                await asyncio.sleep(200/1000)
                updated_count, skipped_count = await self.scrapVoleLeagues(
                    page=page, tenantKey=tenantKey, tournamentName=tournamentName
                )
                await browser.close()
            message = (
                f'voleHrefUpdate tenantKey={tenantKey} tournamentName={tournamentName} '
                f'updated={updated_count} unchanged={skipped_count}'
            )
            self.logger.info(message)
            return True, message
        except Exception as ex:
            self.logger.error(f'voleHrefUpdate error={ex}')
            return False, str(ex)

    async def clickCookie(self, page):
        cookiesBtn = page.locator(f"button#closeCookiesBtn")
        if cookiesBtn and await cookiesBtn.count() == 1 and await cookiesBtn.is_visible():
            await cookiesBtn.click()
            await asyncio.sleep(100/1000)

    async def getTournamentGamesUrl(self, page, tournament, round, fixture, fromFixture = None) -> list:
        tournamentGames = []
        try:
            if not tournament.get('href'):
                return None
            url = f"{self.protocol}{self.baseUrl}{tournament['href']}"
            page = await self.gotoUrl(page=page, url=url)
            await asyncio.sleep(200/1000)

            await self.clickCookie(page=page)

            roundLocator = page.locator(f"select#ddlBoxes")
            cnt = await roundLocator.count()
            if roundLocator and await roundLocator.count() == 1:
                currentSelectedRound = await roundLocator.input_value()
                if round == None:
                    round = currentSelectedRound
            roundOptionText = f'סבב {round}'
            fixtureLocator = page.locator(f"select#ddlRounds")   
            _fromFixture = None
            _toFixture = None
            if fixtureLocator and await fixtureLocator.count() == 1 and await fixtureLocator.is_visible():
                currentSelectedFixture = await fixtureLocator.input_value()
                fixture = fixture or int(currentSelectedFixture)
                if fromFixture:
                    if fromFixture > 0:
                        _fromFixture = max(1, fromFixture)
                    else:
                        _fromFixture = max(1, fixture + fromFixture)
                else:
                    _fromFixture = max(1, fixture)
                _toFixture = fixture + 1
            if roundLocator and await roundLocator.count() == 1:
                roundOptions = roundLocator.locator('option')
                cnt = await roundOptions.count()
                roundOptionsTexts = [await roundOptions.nth(i).text_content() for i in reversed(range(cnt))]
                roundOptionsValues = [await roundOptions.nth(i).get_attribute("value") for i in reversed(range(cnt))]

                continueToNextRound = True
                for roundOptionValue in roundOptionsValues:
                    currentRound = re.search(r'\d+', roundOptionValue).group()
                    if True or roundOptionText in roundOptionsTexts:
                        await roundLocator.select_option(roundOptionValue)#, timeout=15000)
                        #page.select_option("select#multi-select-id", "option_value_1")
                        #await roundLocator.select_option(label=roundOptionText)#, timeout=15000)
                        await asyncio.sleep(100/1000)
                    cnt = await fixtureLocator.count()
                    fixtureVisible = await fixtureLocator.is_visible()
                    if fixtureLocator and await fixtureLocator.count() == 1:
                        fixtureOptions = fixtureLocator.locator('option')
                        cnt = await fixtureOptions.count()
                        for i in range(await fixtureOptions.count()):
                            fixtureOption = fixtureOptions.nth(i)
                            fixtureOptionsText = await fixtureOption.text_content()
                            currentFixture = re.search(r'\d+', fixtureOptionsText).group()
                            #fixtureOptionsText == fixtureOptionText or 
                            if _fromFixture and int(currentFixture) < _fromFixture:
                                continue
                            if _toFixture and int(currentFixture) > _toFixture:
                                continueToNextRound = False
                                break
                            fixtureOptionText = f'מחזור {currentFixture}'
                            if fixtureVisible:
                                await fixtureLocator.select_option(label=fixtureOptionText)#, timeout=15000)
                                await asyncio.sleep(300/1000)
            
                            # Locate all matching <a class="table_row"> elements
                            aGamesRows = await page.locator("a.table_row[data-team1][data-team2]").all()
                            divGamesRows = await page.locator("div.table_row[data-team1][data-team2]").all()
                            gamesRows = aGamesRows + divGamesRows
                            count = len(gamesRows)

                            i = 0
                            for gameRow in gamesRows:
                                try:
                                    i+=1
                                    #gameRow = gamesRows.nth(i)
                                    gameText = await gameRow.inner_text()
                                    homeTeamId = await gameRow.get_attribute("data-team1")
                                    guestTeamId = await gameRow.get_attribute("data-team2")
                                    gameTitle = re.search(r'משחק\s*(.*?)\s*מגרש', gameText, re.DOTALL).group(1).strip().replace('\xa0', ' ')
                                    homeTeamName = gameTitle.split(' - ')[0].strip()
                                    guestTeamName = gameTitle.split(' - ')[1].strip()
                                    #'live, דקה\n71\nתאריך\n25/04/2026\t\nמשחק\nבני יהודה ת\'א - הפ\' פתח תקוה ד"ר בכר'
                                    # get homeTeamName and guestTeamName from gameText after text of משחק
                                    if 'live' in gameTitle or 'חופשית' in gameTitle or 'מנצחת' in gameTitle or 'מפסידת' in gameTitle:
                                        continue
                                    fieldName = re.search(r'מגרש\s*(.*?)\s*שעה', gameText, re.DOTALL).group(1).strip()
                                    gameDate = re.search(r'תאריך\s*(.*?)\s*משחק', gameText, re.DOTALL).group(1).strip()
                                    #gameDate = re.search(r'תאריך\s*(.*?)\s*\n', gameText, re.DOTALL).group(1).strip()
                                    #gameTime = re.search(r'שעה\s*(.*?)\s*\n', gameText, re.DOTALL).group(1).strip()
                                    mt = re.search(r'שעה\s*(.*?)(?:\t|\s*\n|\s*$)', gameText, re.DOTALL)
                                    gameTime = mt.group(1).strip() if mt else ''
                                    gameResult = None
                                    score_m = re.search(
                                        r'תוצאה\s*\n?\s*(\d+)\s*-\s*(\d+)', gameText, re.DOTALL
                                    )
                                    if score_m:
                                        homeTeamScore = score_m.group(2).strip()
                                        guestTeamScore = score_m.group(1).strip()
                                        gameResult = {
                                            'full_time': [homeTeamScore, guestTeamScore]
                                        }
                                    gameUrl = await gameRow.get_attribute("href")
                                    internalGameId = None
                                    if gameUrl:
                                        gameUrl = f'{self.protocol}{self.baseUrl}{gameUrl}'
                                        query = urlparse(gameUrl).query
                                        params = parse_qs(query)
                                        internalGameId = params.get('game_id', 0)[0]
                                    dt = gameDate
                                    if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', gameTime):
                                        gameTime = None
                                    if gameTime:
                                        dt += f' {gameTime}'
                                    tournamentGame = {
                                        'tournamentName': tournament['tournamentName'],
                                        'date': helpers.convert_to_datetime(dt),
                                        'round': currentRound,
                                        'fixture': currentFixture,
                                        'field': fieldName,
                                        'gameTitle': gameTitle,
                                        'homeTeamId': homeTeamId,
                                        'homeTeamName': homeTeamName,
                                        'guestTeamId': guestTeamId,
                                        'guestTeamName': guestTeamName,
                                        'gameResult': gameResult,
                                        'internalGameId': internalGameId,
                                        'url': gameUrl
                                    }
                                    tournamentGame['gamePk'] = self.getPk(objType='games', obj=tournamentGame)
                                    tournamentGames.append(tournamentGame)
                                except Exception as ex:
                                    self.logger.warning(f'getTournamentGamesUrl gameRow={gameRow} error={ex}')

                        if not continueToNextRound:
                            break
        
        except Exception as ex:
            self.logger.error(f'getGamesUrl url={url}', ex)
            return None

        return tournamentGames

    async def refreshTournamentGame(self, tenantKey, page, tournamentName, gameDetail) -> bool:
        if not gameDetail.get('url'):
            return False
            
        try:
            await self.clickCookie(page=page)

            now = helpers.localNow()
            game_date = gameDetail.get('date')
            if game_date is not None:
                if isinstance(game_date, str):
                    try:
                        game_date = datetime.fromisoformat(game_date)
                    except ValueError:
                        game_date = helpers.convert_to_datetime(game_date)
                if isinstance(game_date, datetime) and now < helpers.ensure_aware(game_date):
                    return False
            gameUrl = gameDetail['url']
            scrapGameDetails = await self.scrapGameDetails(page=page, gameUrl=gameUrl)
            if (
                not gameDetail.get('squads') or 
                not scrapGameDetails.get('squads') or
                jsonHelper.save_to_json(gameDetail['squads']) != jsonHelper.save_to_json(scrapGameDetails['squads'])
            ):
                gameDetail['squads'] = scrapGameDetails.get('squads')
                gameDetail['squads']['updatedAt'] = now
            
            if 'referees' not in gameDetail:
                gameDetail['referees'] = []
            gameDetailRefereeNames = [referee['* name'] for referee in gameDetail.get('referees')]
            for referee in scrapGameDetails.get('referees'):
                refName = referee['name']
                internalRefereeId = referee['refereeId']
                globalReferee = self.globalRefereesByName.get(refName)
                phoneIdentifier = None
                if globalReferee and len(globalReferee) == 1:
                    # Unambiguous name match against an already-known referee - reuse their
                    # identity and keep this tenant's internalRefereeId current.
                    matchedRefereeId = globalReferee[0].get('refereeId')
                    phoneIdentifier = globalReferee[0].get('mobileNo') or str(matchedRefereeId)
                    self._linkRefereeToTenant(tenantKey=tenantKey, refereeId=matchedRefereeId, internalRefereeId=internalRefereeId)
                elif not globalReferee:
                    # No name match at all - reuse a referee already created for this
                    # internalRefereeId (this run or a previous one) rather than create a
                    # duplicate, else create a real referee row with no mobile number yet.
                    matchedRefereeId = (self.refereesByInternalId.get(tenantKey) or {}).get(internalRefereeId, {}).get('refereeId')
                    if not matchedRefereeId:
                        newValue, created = self.cacheService.dbClient.setRefereeProperties(value={'name': refName})
                        matchedRefereeId = newValue.get('refereeId') if created else None
                    if matchedRefereeId:
                        self._linkRefereeToTenant(tenantKey=tenantKey, refereeId=matchedRefereeId, internalRefereeId=internalRefereeId, default_status='draft')
                        self.refereesByInternalId.setdefault(tenantKey, {})[internalRefereeId] = {'refereeId': matchedRefereeId, 'name': refName}
                        phoneIdentifier = str(matchedRefereeId)
                # else: ambiguous name match (multiple referees share this name) - leave
                # unresolved rather than guessing, matching prior behavior.
                if refName not in gameDetailRefereeNames:
                    ref = { 'role': referee['role'], '* name': refName, '* phone': phoneIdentifier }
                    gameDetail['referees'].append(ref)

            if (
                not gameDetail.get('gameResult') or 
                not scrapGameDetails.get('gameResult') or
                jsonHelper.save_to_json(gameDetail['gameResult']) != jsonHelper.save_to_json(scrapGameDetails['gameResult'])
            ):
                gameDetail['gameResult'] = scrapGameDetails.get('gameResult')
                gameDetail['gameResult']['updatedAt'] = now
            
            gameDetail['lastGameDetailsRefresh'] = now
            self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gameDetail['gamePk'], value=gameDetail)
        except Exception as ex:
            self.logger.error(f'refreshTournamentGame error={ex}')
            return False

        return True

    async def scrapGameDetails(self, page, gameUrl):
        # Navigate to the URL
        page = await self.gotoUrl(page, gameUrl)
        
        async def scrapGameResult(page):
            """Extract game result (full time and half time scores)"""
            import re
            
            try:
                full_time_score = None
                half_time_score = None
                
                # Get full time score from div class="total"
                try:
                    total_elements = page.locator('div.total')
                    score = await total_elements.evaluate('''
                        (divElement) => {
                            let scoreText = '';
                            for (const node of divElement.childNodes) {
                                if (node.nodeType === 3) { // nodeType 3 is a Text Node
                                    scoreText += node.textContent;
                                }
                            }
                            return scoreText.trim(); // Trim whitespace from the result
                        }
                    ''', timeout=50)
                    if score:
                        full_time_score = score.replace(' ', '').replace('-', ':').split(':')
                except Exception as e:
                    self.logger.debug(f"Error getting full time score from div.total: {str(e)}")
                
                # Get half time score from div class="result-half"
                try:
                    half_time_elements = page.locator('div.result-half')
                    score = await half_time_elements.evaluate('''
                        (divElement) => {
                            let scoreText = '';
                            let idx = 0;
                            for (const node of divElement.childNodes) {
                                if (node.nodeType === 3) { // nodeType 3 is a Text Node
                                    if (idx > 0) {
                                        scoreText += node.textContent;
                                    }
                                    idx++;
                                }
                            }
                            return scoreText.trim(); // Trim whitespace from the result
                        }
                    ''', timeout=50)
                    if score:
                        half_time_score = score.replace(' ', '').replace('-', ':').split(':')
                except Exception as e:
                    self.logger.debug(f"Error getting half time score from div.result-half: {str(e)}")
                            
                return {
                    'full_time': full_time_score.split(':'),
                    'half_time': half_time_score.split(':')
                }

            except Exception as e:
                self.logger.debug(f"Error scraping game result: {str(e)}")
                return {
                    'full_time': None,
                    'half_time': None
                }
                
        async def scrapTeamSectionDetails(page, ariaAttributeValue=None, coach=False, container_css=None):
            if container_css:
                div = page.locator(container_css)
            elif ariaAttributeValue:
                div = page.locator(f"div[aria-labelledby='{ariaAttributeValue}']")
            else:
                return None

            # Ensure the div exists before continuing
            if await div.count() == 0:
                return None

            # Team sections use div.player; referees (div.judge) use a.player — class .player covers both
            playerSpans = div.locator(".player span, .player b")
            spansText = []
            for i in range(await playerSpans.count()):
                playerSpan = playerSpans.nth(i)
                playerSpanChildren = playerSpan.locator(":scope > *")
                c = await playerSpanChildren.count()
                text = await playerSpan.inner_text()
                if coach and c > 0:
                    continue
                spansText.append(text)
            #spansText = [(await playerSpans.nth(i).inner_text()) for i in range(await playerSpans.count())]
            return spansText

        def parsePlayersSpans(playersSpans):
            players = {}
            player = {}

            if playersSpans:
                for span in playersSpans:
                    if "מס'" in span:
                        no = int(span.replace("מס'", "").strip())
                        player = { 'no': no }
                        players[str(no)] = player
                    elif len(player) <= 1:
                        name = span
                        if "- (GK)" in name:
                            name = name.replace("- (GK)", "").strip()
                            player['gk'] = True 
                        if "- (C)" in name:
                            name = name.replace("- (C)", "").strip()
                            player['c'] = True 
                        player['name'] = name
                    elif span == '':
                        continue
                    else:
                        arr = span.split('\n')
                        if len(arr) < 3:
                            continue
                        if arr[0] == "יצא":
                            player['subOut'] = int(arr[2])
                        elif arr[0] == "נכנס":
                            player['subIn'] = int(arr[2])
                        if arr[0] == "כרטיס צהוב":
                            player['yellowCard'] = int(arr[2])
                        elif arr[0] == "כרטיס אדום":
                            player['subIn'] = int(arr[2])
                
            return players

        def parseRefereeSpans(refSpans):
            """Pairs of (name, role) from div.judge a.player b.name / span.position order."""
            if not refSpans:
                return []
            referees = []
            i = 0
            while i + 1 < len(refSpans):
                name = refSpans[i].strip()
                role = refSpans[i + 1].strip()
                referees.append({'name': name, 'role': role})
                i += 2
            return referees

        async def attachRefereeIds(page, referees):
            judge = page.locator('div.judge')
            if await judge.count() == 0 or not referees:
                return referees
            links = judge.locator('a.player')
            n = await links.count()
            for i, ref in enumerate(referees):
                if i >= n:
                    break
                href = await links.nth(i).get_attribute('href')
                if not href:
                    continue
                q = parse_qs(urlparse(href).query)
                rid = (q.get('referee_id') or [None])[0]
                if rid:
                    try:
                        ref['refereeId'] = int(rid)
                    except ValueError:
                        pass
            return referees

        def formatPlayers(players):
            sortedPlayers = dict(sorted(players.items(), key=lambda player: player[1]['no']))
            captainPlayer = next((key for key, value in players.items() if value.get('c') == True), None)
            goalkeeperPlayer = next((key for key, value in players.items() if value.get('gk') == True), None)
            formatedPlayers = []
            if captainPlayer:
                formatedPlayers.append(str(captainPlayer))
            if goalkeeperPlayer:
                formatedPlayers.append(str(goalkeeperPlayer))
            formatedPlayers += [f"{sortedPlayers[playerNo]['no']}" for playerNo in sortedPlayers  if (not captainPlayer or playerNo != captainPlayer) and (not goalkeeperPlayer or playerNo != goalkeeperPlayer)]
            return formatedPlayers

        # Scrape game result
        game_result = await scrapGameResult(page)
        
        homeActiveSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_ACTIVE_HOME')
        homeReplacementSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Replacement_HOME')
        homeBenchSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Bench_HOME')
        homeCoachSpans = await scrapTeamSectionDetails(page, 'GAME_COACH_HOME', True)
        awayActiveSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_ACTIVE_GUEST')
        awayReplacementSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Replacement_GUEST')
        awayBenchSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Bench_GUEST')
        awayCoachSpans = await scrapTeamSectionDetails(page, 'GAME_COACH_GUEST', True)
        refereeSpans = await scrapTeamSectionDetails(page, container_css='div.judge')
        referees = parseRefereeSpans(refereeSpans or [])
        referees = await attachRefereeIds(page, referees)

        homeActivePlayers = parsePlayersSpans(homeActiveSpans)
        homeReplacementPlayers = parsePlayersSpans(homeReplacementSpans)
        homeBenchPlayers = parsePlayersSpans(homeBenchSpans)
        homeCoach = homeCoachSpans[1] if homeCoachSpans else ''
        awayActivePlayers = parsePlayersSpans(awayActiveSpans)
        awayReplacementPlayers = parsePlayersSpans(awayReplacementSpans)
        awayBenchPlayers = parsePlayersSpans(awayBenchSpans)
        awayCoach = awayCoachSpans[1] if awayCoachSpans else ''

        formatedHomeActivePlayers = formatPlayers(homeActivePlayers)
        homeActivePlayersNos = ','.join(formatedHomeActivePlayers)
        formatedHomeReplacementPlayers = formatPlayers(homeReplacementPlayers)
        homeReplacementPlayersNos = ','.join(formatedHomeReplacementPlayers)
        formatedHomeBenchPlayers = formatPlayers(homeBenchPlayers)
        homeBenchPlayersNos = ','.join(formatedHomeBenchPlayers)
        formatedAwayActivePlayers = formatPlayers(awayActivePlayers)
        awayActivePlayersNos = ','.join(formatedAwayActivePlayers)
        formatedAwayReplacementPlayers = formatPlayers(awayReplacementPlayers)
        awayReplacementPlayersNos = ','.join(formatedAwayReplacementPlayers)
        formatedAwayBenchPlayers = formatPlayers(awayBenchPlayers)
        awayBenchPlayersNos = ','.join(formatedAwayBenchPlayers)
 
        squads = { 'homeActivePlayers': homeActivePlayers, 'homeReplacementPlayers': homeReplacementPlayers, 'homeBenchPlayers': homeBenchPlayers, 'homeCoach': homeCoach, \
                    'homeActivePlayersNos': homeActivePlayersNos, 'homeReplacementPlayersNos': homeReplacementPlayersNos, 'homeBenchPlayersNos': homeBenchPlayersNos, \
                    'awayActivePlayers': awayActivePlayers, 'awayReplacementPlayers': awayReplacementPlayers, 'awayBenchPlayers': awayBenchPlayers, 'awayCoach': awayCoach, \
                    'awayActivePlayersNos': awayActivePlayersNos, 'awayReplacementPlayersNos': awayReplacementPlayersNos, 'awayBenchPlayersNos': awayBenchPlayersNos
                }

        return { 'squads': squads, 'referees': referees, 'gameResult': game_result }

    async def scrapVoleLeaguesData(self, page):
        for tournamentName, tournament in self.cacheService.getTournaments().items():
            league = tournament
            if not league.get('voleHref'):
                continue
            if self.cacheService.get_section_by_name(sectionName=league['section'])['tableResult'] == 'Vole':
                leagueData = await self.getVoleLeagueData(page, league['voleHref'])
                self.cacheService.setLeagueTable(tournamentName, leagueData)

            self.logger.info(f'{league} => {len(leagueData)}')

        #helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

    async def scrapLeaguesData(self, page):
        for tournamentName, league in self.cacheService.getTournaments().items():
            if not league.get('href'):
                continue
            leagueData = await self.getIFALeagueData(page, league['href'])
            if self.cacheService.get_section_by_name(sectionName=league['section'])['tableResult'] == True:
                self.cacheService.setLeagueTable(tournamentName=tournamentName, value=leagueData)

            self.logger.info(f'{tournamentName} => {len(leagueData)}')

    async def scarpCupList(self, page, submenu_locator):
        submenu_items = await submenu_locator.query_selector_all("li")
        cupsList = []
        cups = {}
        cupSection = None
        for item in submenu_items:
            text = (await item.inner_text()).strip()
            link = await item.query_selector("a")
            href = await link.get_attribute("href") if link else None
            query = urlparse(href).query
            params = parse_qs(query)
            nationalCupId = int(params.get('national_cup_id', 0)[0])
            name = text
            if nationalCupId == 0:
                cupSection = text[:text.find('\n')]
                #cupSection = await fix_women_leagues(leagueSection, text)
            else:
                cupsList.append({ 'text': text, 'section': cupSection, 'nationalCupId': nationalCupId, 'rules': '', 'href': href})

        for cup in cupsList:
            name = await self.getLeagueName(page, cup['href'])
            #leagueData = await getLeagueData(page, cup['href'])
            cups[name] = cup
            #if sections[cup['section']]['tableResult'] == True:
            #    cups[name]['table'] = leagueData

            self.logger.debug(f'{name}')
        
        return cups

    async def getClassName(self, page):
        # Using locator API (more modern and flexible)
        h2_locator = page.locator('h2').filter(has_text='אישור שיבוצים').first
        if await h2_locator.count() > 0:
            class_name = await h2_locator.get_attribute('class')
            return class_name
        return None

    async def approveGame(self, refereeData, gameId, page, statusCell) -> tuple[bool, str]:
        try:
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            refereeDetail = self.cacheService.getReferees(tenantKey=gameDetail['tenantKey'], mobileNo=refereeData['mobileNo'])
            className = await self.getClassName(page)
            self.logger.info(f'approveGame refId={refereeDetail["refId"]} gameId={gameId} title={page.url} className={className}')
            if not statusCell:
                return False, 'status cell not found'
            try:
                selector_repr = repr(statusCell)
                selector_match = re.search(r"selector='([^']+)'", selector_repr)
                if selector_match:
                    selector = selector_match.group(1)
                    newSelector = selector.replace('.ng-tns-c150-1', f'[class*="ng-tns-c150"]')
                    statusCell = page.locator(newSelector)
                    self.logger.debug(f'Extracted selector: {selector}')
            except Exception as e:
                self.logger.debug(f'Could not extract nth values from statusCell, using defaults: {e}')

            c = await statusCell.count()
            self.logger.debug(f'c={c}')
            if c != 1:
                return False, 'status cell not found on page'
            await statusCell.click()
            inputsLocators = page.locator("input.circle[name='confirm']")
            if await inputsLocators.count() != 2:
                return False, 'approve confirm controls not found'
            await inputsLocators.nth(0).click()
            noteInputLocator = page.locator("input.custom-input[name='note']")
            if await noteInputLocator.count() == 1:
                await noteInputLocator.nth(0).fill(f'אושר')
            confirmButtonLocator = page.locator("button.btn").filter(has_text="אישור")
            if await confirmButtonLocator.count() == 1:
                await confirmButtonLocator.nth(0).click()
                return True, 'success'
            return False, 'approve confirm button not found'

        except Exception as ex:
            self.logger.error(f'approveGame', ex)
            return False, str(ex)

    async def declineGame(self, refereeData, gameId, page, statusCell) -> tuple[bool, str]:
        return False, 'declineGame not implemented for IFA'

    async def generatePostGameUpdateTemplate(self, gameDetail):
        tenantKey = gameDetail['tenantKey']
        tournamentName = gameDetail['tournamentName']
        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
        gameDuration = int(gameDetail['gameDuration'])
        breakTime = None
        rules = None
        if tournament and tournament.get('rules'):
            rules = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules').strip())
            match = re.search(r"\d+", (rules.game or {}).get('זמני מחצית', '') if rules else '')
            if match:
                breakTime = int(match.group())
        msg = f'**סיכום משחק**'
        msg += f'\nמסגרת משחקים: {gameDetail["tournamentName"]}'
        msg += f'\nקבוצות: {gameDetail["homeTeamName"]}-{gameDetail["guestTeamName"]}'
        msg += f'\nמזהה: {gameDetail["id"]}'
        startTime = gameDetail['date'].strftime("%H:%M")
        endTime = (gameDetail['date'] + timedelta(minutes=gameDuration)).strftime("%H:%M")
        msg += f'\nפתיחה:\n{startTime}'
        msg += f'\nסיום:\n{endTime}'
        msg += f'\nהפסקה:\n{breakTime}'
        msg += f'\nתוספת זמן:\n{1}'
        msg += f'\nסיבות לתוספת:\n...'
        msg += f'\nביתית מחצית:\n0'
        msg += f'\nאורחת מחצית:\n0'
        msg += f'\nביתית סיום:\n0'
        msg += f'\nאורחת סיום:\n0'
        msg += f'\nטקסים (ללא/חלקי/מלא):\nמלא'
        msg += f'\nפירוט לטקסים:\n...\n'

        return msg

    from playwright.async_api import Page, Locator
    async def beforeGameUpdateByOrgService(self, refereeDetail, gameId, data, page) -> tuple[bool, str]:
        try:
            self.logger.info(f'beforeGameUpdateByOrgService refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            internalGameId = gameDetail.get('internalGameId')
            if not internalGameId:
                return False, 'internalGameId not found'
            #url1 = 'https://ref.football.org.il/referee/game-reports/1101751'
            url = f"{self.gameReportsUrl}/{internalGameId}"
            result = await page.goto(url)
            await page.wait_for_load_state('networkidle')
            if url != page.url:
                return False, 'url mismatch'
            
            return True, 'success'
        except Exception as ex:
            self.logger.error(f'beforeGameUpdateByOrgService', ex)
            return False, str(ex)

    async def afterGameUpdateByOrgService(self, refereeDetail, gameId, data, page):
        try:
            self.logger.info(f'afterGameUpdateByOrgService refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            confirmLocator = await self.getLocator(parent=page, selector="button.confirm")
            if confirmLocator:
                await confirmLocator.click()
                return True

        except Exception as ex:
            self.logger.error(f'afterGameUpdateByOrgService', ex)

        return False

    async def getUnfinishedGameReports(self, page, refereeDetail):
        """Scrape the 'משחקים אשר דוחות עבורם לא נקלטו או לא הושלמו' table on the referee
        home page. Returns a dict keyed by gamePk; each entry adds homeTeamName/guestTeamName
        (split from the combined 'gameTitle' column) and a 'statusCell' locator that opens
        the game report form when clicked."""
        page = await self.gotoUrl(page=page, url=self.gamesUrl)
        await asyncio.sleep(300 * self.latencyFactor / 1000)
        convertResults = await self.convertGamesReportsTableToText(page=page, refereeDetail=refereeDetail)
        if not convertResults:
            return {}
        gamesReports = await self.parseText(tenantKey=refereeDetail['tenantKey'], objType='gamesReports', convertResults=convertResults)
        for report in (gamesReports or {}).values():
            homeTeamName, guestTeamName = self._splitGameReportTeams(report.get('gameTitle'))
            report['homeTeamName'] = homeTeamName
            report['guestTeamName'] = guestTeamName
            report['statusCell'] = report.get('cells', {}).get('status')
        return gamesReports or {}

    def _splitGameReportTeams(self, gameTitle):
        if not gameTitle or ':' not in gameTitle:
            return None, None
        homeTeamName, guestTeamName = gameTitle.split(':', 1)
        return homeTeamName.strip(), guestTeamName.strip()

    def findUnfinishedGameReport(self, gamesReports, date=None, tournamentName=None, homeTeamName=None, guestTeamName=None, fixture=None, field=None):
        """Find a row scraped by getUnfinishedGameReports() matching the given date/time,
        tournament, home/guest team names, fixture and field. Any criterion left as None is
        not filtered on."""
        if isinstance(date, str):
            date = helpers.convert_to_datetime(date)
        tournamentName = self.fixNameQuote(tournamentName).strip() if tournamentName else None
        homeTeamName = self.fixNameQuote(homeTeamName).strip() if homeTeamName else None
        guestTeamName = self.fixNameQuote(guestTeamName).strip() if guestTeamName else None
        fixture = str(fixture).strip() if fixture is not None else None
        field = field.strip() if field else None

        for report in (gamesReports or {}).values():
            if date and report.get('date') != date:
                continue
            if tournamentName and self.fixNameQuote(report.get('tournamentName') or '').strip() != tournamentName:
                continue
            if homeTeamName and self.fixNameQuote(report.get('homeTeamName') or '').strip() != homeTeamName:
                continue
            if guestTeamName and self.fixNameQuote(report.get('guestTeamName') or '').strip() != guestTeamName:
                continue
            if fixture and str(report.get('fixture') or '').strip() != fixture:
                continue
            if field:
                reportField = (report.get('field') or '').strip()
                if field != reportField and field not in reportField and reportField not in field:
                    continue
            return report

        return None

    async def openUnfinishedGameReportForm(self, page, statusCell) -> tuple[bool, str]:
        """Click the status link of a row from getUnfinishedGameReports() and wait for the
        game report form (referee/game-reports/{id}) to open."""
        try:
            if not statusCell:
                return False, 'statusCell not found'
            await statusCell.click()
            await page.wait_for_url(re.compile(r'.*/referee/game-reports/\d+'), timeout=15000)
            await page.wait_for_selector("button.confirm", timeout=15000)
            return True, 'opened'
        except Exception as ex:
            self.logger.error('openUnfinishedGameReportForm', ex)
            return False, str(ex)

    async def submitUnfinishedGameReport(self, refereeDetail, page, data, date=None, tournamentName=None, homeTeamName=None, guestTeamName=None, fixture=None, field=None, beforeConfirm=None) -> tuple[bool, str]:
        """
        Scrape the 'משחקים אשר דוחות עבורם לא נקלטו או לא הושלמו' table, find the row matching
        date/time, tournament, home/guest team names, fixture and field, click its status link
        to open the game report form, fill in the given fields and submit by clicking 'המשך'.

        data: dict of friendly field name -> value, using the keys in self.gameReportFieldMap:
            {
                'startTime': '19:00',            # זמן התחלת משחק
                'endTime': '20:45',               # זמן גמר משחק
                'breakMinutes': '15',             # משך הפסקה (דקות)
                'addedTimeMinutes': '2',           # תוספת זמן (דקות)
                'addedTimeReason': 'פציעת שחקן',   # סיבות לתוספת זמן
                'homeScore': '2',                  # תוצאה - קבוצה ביתית (בסיום)
                'guestScore': '1',                 # תוצאה - קבוצה אורחת (בסיום)
                'homeHTScore': '1',                 # תוצאה - קבוצה ביתית (מחצית), league/cup games only
                'guestHTScore': '0',                # תוצאה - קבוצה אורחת (מחצית), league/cup games only
            }
        Unrecognized keys are treated as raw CSS selectors, so callers can still target any
        other field directly (optionally with '@N' for the Nth match, or a trailing '!' to skip).

        beforeConfirm: optional async callable(page) invoked after all fields are filled but
        before clicking 'המשך' — e.g. `await page.pause()` for a manual human review checkpoint
        before this submits a real report.
        """
        try:
            gamesReports = await self.getUnfinishedGameReports(page=page, refereeDetail=refereeDetail)
            if not gamesReports:
                return False, 'No unfinished game reports found'

            report = self.findUnfinishedGameReport(
                gamesReports=gamesReports, date=date, tournamentName=tournamentName,
                homeTeamName=homeTeamName, guestTeamName=guestTeamName, fixture=fixture, field=field
            )
            if not report:
                return False, 'Game not found in unfinished game reports table'

            opened, message = await self.openUnfinishedGameReportForm(page=page, statusCell=report.get('statusCell'))
            if not opened:
                return False, message

            await asyncio.sleep(300 * self.latencyFactor / 1000)

            for fieldName, value in (data or {}).items():
                selector = self.gameReportFieldMap.get(fieldName, fieldName)
                if selector.endswith('!'):
                    continue
                selectorPart, occurrence = (selector.split('@') + ['0'])[:2]
                locator = page.locator(selectorPart).nth(int(occurrence))
                if await locator.count() == 0 or not await locator.is_visible() or await locator.is_disabled():
                    continue
                tag = await locator.evaluate("el => el.tagName.toLowerCase()")
                if tag in ('input', 'textarea'):
                    await locator.fill(str(value))
                elif tag == 'select':
                    selectOptions = locator.locator('option')
                    for k in range(await selectOptions.count()):
                        selectOption = selectOptions.nth(k)
                        selectOptionValue = await selectOption.get_attribute("value")
                        selectOptionText = await selectOption.text_content()
                        if str(value) in selectOptionText:
                            await locator.select_option(value=selectOptionValue)
                            break
                await asyncio.sleep(150 * self.latencyFactor / 1000)

            if beforeConfirm:
                await beforeConfirm(page)

            confirmButton = page.locator("button.confirm")
            if await confirmButton.count() == 0:
                return False, 'confirm button not found'
            await confirmButton.click()
            return True, 'submitted'
        except Exception as ex:
            self.logger.error('submitUnfinishedGameReport', ex, refereeDetail=refereeDetail)
            return False, str(ex)

    async def postGameReport(self, refereeDetail, gameId, data, page) -> tuple[bool, str]:
        pass

    async def postGameUpdate1(self, refereeDetail, gameId, data, page, statusCell):
        try:
            self.logger.info(f'postGameUpdate refId={refereeDetail["refereeId"]} gameId={gameId} title={page.url}')
            if statusCell:
                await statusCell.click()
                await asyncio.sleep(1000/1000)
                confirmButtonLocator = await self.getLocator(page, "button.confirm")
        
                for controlName, controlValue in data.items():
                    ctrlValue = controlValue if controlValue else ' '
                    ctrlName = controlName.split('#')[0]
                    ctrlExpectedCount = len([key for key in data.keys() if key.split('#')[0] == ctrlName])
                    seq = int(controlName.split('#')[1]) if '#' in controlName else 0
                    locators = page.locator(f"[formcontrolname='{ctrlName}']")
                    j = 0
                    controlCount = await locators.count()
                    for i in range(controlCount):
                        locator = locators.nth(i)
                        if (await locator.is_visible()) == False or await locator.is_disabled():
                            continue
                        if j != seq and controlCount > 1 or controlCount != ctrlExpectedCount and seq == 0:
                            j += 1
                            continue
                        tag = await locator.evaluate("el => el.tagName.toLowerCase()")
                        if tag == 'input':
                            hasAppNumbersOnly = await locator.get_attribute("appnumbersonly") is not None
                            await locator.fill(ctrlValue)
                        elif tag == 'select':
                            controlOptions = locator.locator('option')
                            for k in range(await controlOptions.count()):
                                controlOption = controlOptions.nth(k)
                                controlOptionValue = await controlOption.get_attribute("value")
                                controlOptionText = await controlOption.text_content()
                                if ctrlValue in controlOptionText:
                                    await locator.select_option(value=controlOptionValue)#, timeout=15000)
                                    await asyncio.sleep(200/1000)
                        break

                if confirmButtonLocator:
                    await confirmButtonLocator.click()
                    return True

            return False
        except Exception as ex:
            self.logger.error(f'postGameUpdate', ex)

    async def getPayments(self, refereeDetail, page):
        try:
            self.logger.info(f'getPayments refId={refereeDetail["refId"]} title={page.url}')
            page = await self.gotoUrl(page, self.paymentsUrl)

            payments_data = await self.ifaPaymentScraper.scrape_all_pages(page=page, max_pages=30)
            file_path = f'./payments_{refereeDetail["refId"]}.json'
            jsonHelper.save_to_file(payments_data, f'{file_path}')

            return True
        except Exception as ex:
            self.logger.error(f'getPayments', ex)
            return False

if __name__ == "__main__":
    from shared.appContainer import AppContainer
    from shared.orgRelated.orgServiceFactory import OrgServiceFactory
    container = AppContainer.getAppContainer()
    orgServiceFactory: OrgServiceFactory = container.orgServiceFactory()
    tenantKey = 'IL#football#2025-26'
    ifaService: IFAService = orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)
    asyncio.run(ifaService.voleHrefUpdate(tenantKey=tenantKey))
    exit(0)