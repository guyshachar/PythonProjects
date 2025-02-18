import logging
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path
import asyncio
from urllib.parse import urlencode
import json
from bs4 import BeautifulSoup
import html2text
from firebase_admin import credentials, messaging
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
from shared.handleUsers import HandleUsers
from shared.mqttClient import MqttClient
from shared.twilioClient import TwilioClient
from playwright.async_api import async_playwright
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from shared.fileWatcher import watchFileChange

class BrowserActions():
    def __init__(self, logger):
        self.app = os.environ.get('app')

        if logger:
            self.logger = logger
        else:            
            # Configure logging
            logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
            logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            self.logger = logging.getLogger(__name__)        

        self.handleUsers = HandleUsers(self.logger)
        self.handleTournaments = HandleTournaments(self.logger)
        self.handleRefereeData = HandleRefereeData(self.logger)

        self.loginUrl = os.environ.get('loginUrl') or 'https://ref.football.org.il/login'
        self.gamesUrl = os.environ.get('gamesUrl') or 'https://ref.football.org.il/referee/home'
        self.reviewsUrl = os.environ.get('reviewsUrl') or 'https://ref.football.org.il/referee/reviews'

        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "tags" : [ 'תאריך', "יום", "מסגרת משחקים", "משחק", "סבב", "מחזור", "מגרש", "סטטוס" ],
                #           "תפקיד", "* שם", "* דרג", "* טלפון", "* כתובת" ],
                "initTag" : 'תאריך',
                "pkTags": [ "מסגרת משחקים", "משחק", "מחזור" ],
                "nestedTags": [ "תפקיד", "* שם", "* סטטוס", "* דרג", "* טלפון", "* כתובת" ],
                "pkNestedTags": "תפקיד",
                "initNestedTag" : 'תפקיד',
                "סטטוסTag": { "name": "סטטוס", "dic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")] },
                "* שםTag": { "name": "* סטטוס", "dic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")] },
           },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "tags" : [ "מס.", 'תאריך', "שעה", "מסגרת משחקים", "משחק", "מגרש", "מחזור", "תפקיד במגרש", "מבקר", "ציון" ],
                "initTag" : "מס.",
                "excludeCompareTags" : [ "מס." ],
                "pkTags": ["מסגרת משחקים", "משחק"]
            }
        }

        self.lastGameAssignment = None
        self.pollingInterval = int(os.environ.get('loadInterval') or '10000')
        self.checkGames = eval(os.environ.get('checkGames') or 'True')
        self.checkReviews = eval(os.environ.get('checkReviews') or 'True')
        self.translation_table = str.maketrans('', '', "!@#'? \"")
        self.openWindowReminder = int(os.environ.get('openWindowReminder') or '18')

        self.swLevel = os.environ.get('swLevel') or 'debug'

        self.apiServiceUrlBase = os.environ.get('apiServiceUrlBase')
        self.approveGames = eval(os.environ.get('approveGames') or 'False')
        twilioServiceId = os.environ.get('twilioServiceId')
        self.twilioFromMobile = os.environ.get('twilioFromMobile')
        self.twilioClient = TwilioClient(self.logger, twilioServiceId=twilioServiceId, fromMobile=self.twilioFromMobile)
        self.twilioUseTemplate = eval(os.environ.get('twilioUseTemplate') or 'False')
        self.twilioUseFreeText = eval(os.environ.get('twilioUseFreeText') or 'False')
        self.twilioSend = eval(os.environ.get('twilioSend') or 'False')
        self.twilioNewGameContentSid = os.environ.get('twilioNewGameContentSid')
        self.twilioGameUpdateContentSid = os.environ.get('twilioGameUpdateContentSid')
        self.twilioGameNoticeContentSid = os.environ.get('twilioGameNoticeContentSid')
        
        self.refIdsPartition = (os.environ.get('refIdsPartition') or '1,2,3,4,5,6,7,8,9,0').split(',')
   
    async def convertGamesTableToText(self, page, refereeDetail):
        games = "games"
        results = []

        try:
            '''
            if html == None:
                results.append({'text':'אין שיבוצים'})
                return results
            '''
            tablesLocator = page.locator('table.ng-tns-c150-1')
            cnt = await tablesLocator.count()
            self.logger.debug(helpers.colorText(refereeDetail, f'convertGamesTableToText/tablesLocator={cnt}'))
            if cnt == 0: #Still need to investigate this scenario
                return results
            
            if cnt == 1:
                gamesTable = tablesLocator.nth(0)
                rowsLocator = gamesTable.locator('tr')
                cnt = await rowsLocator.count()
                self.logger.debug(helpers.colorText(refereeDetail, f'convertGamesTableToText/rowsLocator={cnt}'))
                gameRows = [(rowsLocator.nth(i)) for i in range(cnt)]
                
                # Process each subsequent row and map to headers
                if len(gameRows) <= 1:
                    results.append({'text': 'אין שיבוצים'})

                else:
                    gameHeadersLocator = gameRows[0].locator('th')
                    gameHeaders = [(gameHeadersLocator.nth(i)) for i in range(await gameHeadersLocator.count())]
                    gameHeadersTexts = [(await header.inner_text()).strip() for header in gameHeaders]

                    i = 0
                    for gameRow in gameRows[1:]:  # Skip the header row
                        i += 1
                        gameCellsLocator = gameRow.locator('td')
                        gameCells = [(gameCellsLocator.nth(i)) for i in range(await gameCellsLocator.count())]
                        if len(gameCells) == len(gameHeadersTexts):  # Regular rows
                            for gameHeader, gameCell in zip(gameHeadersTexts, gameCells):
                                cellText = (await gameCell.inner_text()).strip()
                                cellHTml = await gameCell.evaluate("element => element.outerHTML")
                                (tagName, tagText) = self.getTagText(games, gameHeader, cellHTml)
                                obj = None

                                await gameCell.evaluate('(element, unique_id) => element.id = unique_id', f'{gameHeader}_{i}')

                                if gameHeader and (cellText or tagText):
                                    obj = {'header': gameHeader, 'text': cellText or tagText, 'cell': gameCell}
                                    results.append(obj)
                                if tagName and cellText and tagText:
                                    obj = {'header': tagName, 'text': tagText, 'cell': gameCell}
                                    results.append(obj)

                        elif len(gameCells) == 1:  # Row with colspan
                            cellHTml = await gameCells[0].evaluate("element => element.outerHTML")
                            transformedHtml = self.transformHtmlTable(cellHTml)
                            #self.logger.warning(str(html1))
                            nestedResult = await self.convertGamesTableToTextUsingSoup(transformedHtml)
                            results.append({'text': ''})
                            for obj in nestedResult:
                                results.append(obj)
                
        except Exception as ex:
            helpers.logError(self.logger, 'convertGamesTableToText', ex, refereeDetail)
            return None
        
        return results

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
            helpers.logError(self.logger, 'convertGamesTableToTextUsingSoup', ex)
            return None

        return results

    async def convertReviewsTableToText(self, page, refereeDetail):
        reviews = "reviews"
        results = []

        try:
            '''
            if html == None:
                results.append({'text':'אין ביקורות'})
                return results
            '''
            tablesLocator = page.locator('table.ng-star-inserted')
            cnt = await tablesLocator.count()
            self.logger.debug(helpers.colorText(refereeDetail, f'convertReviewsTableToText/tablesLocator={cnt}'))
            if cnt == 0: #Still need to investigate this scenario
                return results
            
            if cnt == 1:
                reviewsTable = tablesLocator.nth(0)
                rowsLocator = reviewsTable.locator('tr')
                cnt = await rowsLocator.count()
                self.logger.debug(helpers.colorText(refereeDetail, f'convertReviewsTableToText/rowsLocator={cnt}'))
                reviewRows = [(rowsLocator.nth(i)) for i in range(await rowsLocator.count())]

                reviewHeadersLocator = reviewRows[0].locator('th')
                reviewHeaders = [(reviewHeadersLocator.nth(i)) for i in range(await reviewHeadersLocator.count())]
                reviewHeadersTexts = [(await header.inner_text()).strip() for header in reviewHeaders]
                # Process each subsequent row and map to headers
                if len(reviewRows) <= 1:
                    results.append({'text': 'אין ביקורות'})
                else:
                    i = 0
                    for reviewRow in reviewRows[1:]:  # Skip the header row
                        i += 1
                        reviewCellsLocator = reviewRow.locator('td')
                        reviewCells = [(reviewCellsLocator.nth(i)) for i in range(await reviewCellsLocator.count())]
                        if len(reviewCells) == len(reviewHeadersTexts):  # Regular rows
                            for reviewHeader, reviewCell in zip(reviewHeadersTexts, reviewCells):
                                cellText = (await reviewCell.inner_text()).strip()
                                cellHTml = await reviewCell.evaluate("element => element.outerHTML")
                                (tagName, tagText) = self.getTagText(reviews, reviewHeader, cellHTml)
                                obj = None

                                await reviewCell.evaluate('(element, unique_id) => element.id = unique_id', f'{reviewHeader}_{i}')

                                if reviewHeader and (cellText or tagText):
                                    obj = {'header': reviewHeader, 'text': cellText or tagText, 'cell': reviewCell}
                                    results.append(obj)
                                if tagName and cellText and tagText:
                                    obj = {'header': tagName, 'text': tagText, 'cell': reviewCell}
                                    results.append(obj)

                        elif len(reviewCells) == 1:  # Row with colspan
                            results.append({'text': await reviewCells.nth(0).inner_text()})
                
        except Exception as ex:
            helpers.logError(self.logger, f'convertReviewsTableToText', ex, refereeDetail)
            return None
        
        return results

    async def login(self, refereeDetail, page):
        try:
            t=0
            while page.url != self.gamesUrl and t < 5:
                t+=1
                self.logger.debug(helpers.colorText(refereeDetail, f'login#{t}'))
                try:
                    await helpers.gotoUrl(page, self.loginUrl)
                    await asyncio.sleep(1000*t / 1000)

                    input_elements = await page.query_selector_all('input')
                    if len(input_elements) == 3:
                        usernameField = input_elements[0]
                        await usernameField.fill(refereeDetail["refId"])

                        passwordField = input_elements[1]
                        await passwordField.fill(self.handleUsers.decryptPassword(refereeDetail['password']))

                        idField = input_elements[2]
                        await idField.fill(refereeDetail["id"])

                        await idField.press("Enter")
                        '''
                        # Find the submit button and click it
                        buttonsLocator = page.locator('button')
                        if await buttonsLocator.count() > 0:
                            mainButton = buttonsLocator.nth(0)
                            await mainButton.click()
                        '''
                        await asyncio.sleep(500 / 1000)
                except Exception as ex:
                    helpers.logError(self.logger, 'login', ex, refereeDetail)
            await asyncio.sleep(500 / 1000)

            if page.url != self.gamesUrl:
                self.logger.error(helpers.colorText(refereeDetail, f'Login failed#{t}'))
            else:
                self.logger.debug(helpers.colorText(refereeDetail, f'Login successfull#{t}'))
                return True

        except Exception as ex:
            helpers.logError(self.logger, f'Login', ex, refereeDetail)

        return False
    
    async def logout(self, refereeDetail, page):
        t=0
        
        while page.url != self.loginUrl and t < 3:
            try:
                t+=1
                await helpers.gotoUrl(page, self.loginUrl)
                self.logger.debug(helpers.colorText(refereeDetail, f'logout#{t}'))
                button_elements = await page.query_selector_all("button")
                logoutButtons = [button for button in button_elements if (await button.inner_text()).strip() == "יציאה"]

                self.logger.debug(f'logoutButtons={len(logoutButtons)}')
                if len(logoutButtons) == 1:
                    logoutButton = button_elements[0]
                    await logoutButton.click()
                await asyncio.sleep(1000*t / 1000)
            except Exception as ex:
                pass

        if page.url != self.loginUrl:
            self.logger.error(helpers.colorText(refereeDetail, f'Logout failed#{t}'))
            return False
        else:
            self.logger.debug(helpers.colorText(refereeDetail, f'Logout successfull#{t}'))
    
        return True

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

if __name__ == "__main__":
    app = None
    try:
        #fixTournaments()
        #exit
        print("Hello RefPortalllll")
        browserActions = BrowserActions()
        browserActions.logger.info(f'Main run')
        asyncio.run(browserActions.start())
        pass
    except Exception as ex:
        print(f'Main Error: {ex}')
        pass