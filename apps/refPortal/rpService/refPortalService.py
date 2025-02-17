#from Shared.logger import Logger
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta
import os
import uuid
import sys
from pathlib import Path
import socket
import shutil
import asyncio
from urllib.parse import urlencode
import json
#from html2image import Html2Image
from bs4 import BeautifulSoup
import html2text
import firebase_admin
from firebase_admin import credentials, messaging
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
from shared.handleUsers import HandleUsers
import pageManager
from shared.mqttClient import MqttClient
from shared.twilioClient import TwilioClient
from playwright.async_api import async_playwright
from colorama import Fore, Style
import copy
import shared.handleTournaments as handleTournaments
from shared.fileWatcher import watchFileChange

class RefPortalService():
    def __init__(self):
        self.app = os.environ.get('app')

        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logFormat = f'%(asctime)s - {self.app} - %(name)s - %(levelname)s - %(message)s'
        formatter = logging.Formatter(logFormat)
        logging.basicConfig(level=logLevel, format=logFormat)
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)  # Capture all levels

        logFile = f'{os.getenv("MY_DATA_FILE", "/run/data/")}logs/log-{self.app}.log'
        file_handler = TimedRotatingFileHandler(
            logFile, when="H", interval=1, backupCount=6, encoding="utf-8"
        )        
        #file_handler = logging.FileHandler(logFile)
        file_handler.setLevel(logging.DEBUG)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logLevel) 

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.handlers.clear()
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.logger.propagate = False

        self.fileVersion = os.environ.get('fileVersion') or 'v'
        self.openText=f'Ref Portal Service {helpers.datetime_to_str(datetime.now())} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        self.logger.info(self.openText)
        self.logger.debug(self.openText)

        self.loginUrl = os.environ.get('loginUrl') or 'https://ref.football.org.il/login'
        self.gamesUrl = os.environ.get('gamesUrl') or 'https://ref.football.org.il/referee/home'
        self.reviewsUrl = os.environ.get('reviewsUrl') or 'https://ref.football.org.il/referee/reviews'
        self.IFAUrl = os.environ.get('IFAUrl') or 'www.football.org.il'

        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "processTemplates": self.processTemplatesGames,
                "convert": self.convertGamesTableToText,
                "parse": self.parseText,
                'postParse': self.postParseGames,
                'compare': self.compareList,
                'generate': self.generateGameDetails,
                "actions": self.gamesActions,
                'notify': self.notifyUpdate,
                "notifyTitle" : "שיבוצים:",
                "tags" : [ 'תאריך', "יום", "מסגרת משחקים", "משחק", "סבב", "מחזור", "מגרש", "סטטוס" ],
                #           "תפקיד", "* שם", "* דרג", "* טלפון", "* כתובת" ],
                "initTag" : 'תאריך',
                "pkTags": [ "מסגרת משחקים", "משחק", "מחזור" ],
                "nestedTags": [ "תפקיד", "* שם", "* סטטוס", "* דרג", "* טלפון", "* כתובת" ],
                "pkNestedTags": "תפקיד",
                "initNestedTag" : 'תפקיד',
                "סטטוסTag": { "name": "סטטוס", "dic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")] },
                "* שםTag": { "name": "* סטטוס", "dic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")] },
                'removeFilter': 'תאריך'
           },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "convert": self.convertReviewsTableToText,
                "parse": self.parseText,
                'postParse': self.postParseReviews,
                'compare': self.compareList,
                'generate': self.generateReviewDetails,
                'notify': self.notifyUpdate,
                "notifyTitle" : "ביקורות:",
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

        self.swLevel = os.environ.get('swLevel') or 'debug'

        self.apiServiceUrlBase = os.environ.get('apiServiceUrlBase')
        self.approveGames = eval(os.environ.get('approveGames') or 'False')
        self.start24HoursWindowNotification = eval(os.environ.get('start24HoursWindowNotification') or 'False')
        twilioServiceId = os.environ.get('twilioServiceId')
        self.twilioFromMobile = os.environ.get('twilioFromMobile')
        self.twilioClient = TwilioClient(twilioServiceId=twilioServiceId, fromMobile=self.twilioFromMobile)
        self.twilioUseTemplate = eval(os.environ.get('twilioUseTemplate') or 'False')
        self.twilioUseFreeText = eval(os.environ.get('twilioUseFreeText') or 'False')
        self.twilioSend = eval(os.environ.get('twilioSend') or 'False')
        self.twilioNewGameContentSid = os.environ.get('twilioNewGameContentSid')
        self.twilioGameUpdateContentSid = os.environ.get('twilioGameUpdateContentSid')
        self.twilioGameNoticeContentSid = os.environ.get('twilioGameNoticeContentSid')
        self.handleUsers = HandleUsers()

        self.refIdsPartition = (os.environ.get('refIdsPartition') or '1,2,3,4,5,6,7,8,9,0').split(',')

        self.loadMetadata(True)

        self.concurrentPages = int(os.environ.get('concurrentPages') or '4')
        self.browserRenewal = int(os.environ.get('browserRenewal') or '5')
        self.alwaysRenewPages = eval(os.environ.get('alwaysRenewPages', 'False'))
        self.activeReferees = len(self.activeRefereeDetails)
        if self.activeReferees < self.concurrentPages:
            self.concurrentPages = self.activeReferees

        # Initialize Firebase Admin SDK
        jsonKeyFile = "path/to/your/serviceAccountKey.json"
        if os.path.exists(jsonKeyFile):
            fbCred = credentials.Certificate(jsonKeyFile)
            firebase_admin.initialize_app(fbCred)

        self.mqttPublish = eval(os.environ.get('mqttPublish') or 'True')
        self.mqttClient = MqttClient(parent=self)
        self.mqttTopic = 'my/mqtt/refPortal'
        self.logger.info(f'logLevel={logLevel} url={self.loginUrl} interval={self.pollingInterval} twilio={self.twilioSend} mqtt={self.mqttPublish} pages={self.concurrentPages} approveGames={self.approveGames}')
   
    def updateRefereeAddress(self, refereeDetail, address = None):
        if 'addressDetails' not in refereeDetail or address and address != refereeDetail['addressDetails']['address']:
            refereeDetail['addressDetails'] = { 'address': address, 'coordinates': None}

        if refereeDetail['addressDetails']['address'] and not refereeDetail['addressDetails']['coordinates']:
            coordinates, formattedAddress, error = helpers.get_coordinates_google_maps(refereeDetail['addressDetails']['address'])
            lat, lng = coordinates
            refereeDetail['addressDetails']['coordinates'] = { "lat": lat, "lng": lng}
            refereeDetail['addressDetails']['formattedAddress'] = formattedAddress
            self.writeRefereeDetails(refereeDetail)

    def createIcs(self, refId, game, removal = False):
        gameDesc = self.dataDic['games']['generate'](game)
        field = game.get('מגרש')
        location =''
        if field:
            location = f"{field}, {self.fields[field]['addressDetails'].get('address')}"
        (fileId, icsFile) = helpers.getGameIcsFilename(refId, game['id'])

        helpers.createIcs(f"{game['משחק']}/{game['מסגרת משחקים']}", \
                          game['date'], \
                          2, gameDesc, location, removal, icsFile)
        
        return fileId

    def loadMetadata(self, initial=False):
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}referees/details/referees.json'
            refTemplates_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/'
            fields_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}fields/fields.json'
            sections_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/sections.json'
            tournaments_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/tournaments.json'
            leagueTables_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/'
            rules_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/rules.json'
            games_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/games.json'
            messages_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}messages/messages.json'

            self.refereeFileWatchObserver = watchFileChange(referee_file_path, self.shouldLoadRefereesFile)
            self.refTemplatesFileWatchObserver = watchFileChange(refTemplates_file_path, self.shouldLoadTemplatesFile)
            self.fieldsFileWatchObserver = watchFileChange(fields_file_path, self.shouldLoadFieldsFile)
            self.sectionsFileWatchObserver = watchFileChange(sections_file_path, self.shouldLoadSectionsFile)
            self.tournamentsFileWatchObserver = watchFileChange(tournaments_file_path, self.shouldLoadTemplatesFile)
            self.leagueTablesFileWatchObserver = watchFileChange(leagueTables_file_path, self.shouldLoadLeagueTableFile)
            self.rulesFileWatchObserver = watchFileChange(rules_file_path, self.shouldLoadRulesFile)
            self.gamesFileWatchObserver = watchFileChange(games_file_path, self.shouldLoadGamesFile)
            self.messagesFileWatchObserver = watchFileChange(messages_file_path, self.shouldLoadMessagesFile)

            if initial or self.refereesFileChanged or self.refTemplatesFileChanged and len(self.refTemplatesFileChanged) > 0:
                self.loadActiveRefereeDetails(referee_file_path, None, initial)
            if initial or self.fieldsFileChanged:
                self.loadFields(fields_file_path)
            if initial or self.sectionsFileChanged:
                self.loadSections(sections_file_path)
            if initial or self.tournamentsFileChanged or self.leagueTableFileChanged and len(self.leagueTableFileChanged) > 0:
                self.loadTournaments(tournaments_file_path, None, initial)
            if initial or self.rulesFileChanged:
                self.loadRules(rules_file_path)
            if initial or self.gamesFileChanged:
                self.loadGames(games_file_path)
            if initial or self.messagesFileChanged:
                self.twilioClient.loadMessages(messages_file_path)

            self.refereesFileChanged = False
            self.refTemplatesFileChanged = {}
            self.fieldsFileChanged = False
            self.sectionsFileChanged = False
            self.tournamentsFileChanged = False
            self.leagueTableFileChanged = {}
            self.rulesFileChanged = False
            self.gamesFileChanged = False
            self.messagesFileChanged = False

        except Exception as ex:
            self.logError(f'watchFiles', ex)

    def shouldLoadRefereesFile(self, filePath, file=None):
        self.refereesFileChanged = True
    def shouldLoadTemplatesFile(self, filePath, file=None):
        refId = file[file.find('refId')+5:].rstrip('.json')
        if not refId.isdigit():
            return
        self.refTemplatesFileChanged[refId] = True
    def shouldLoadRefereesFile(self, filePath, file=None):
        self.refereesFileChanged = True
    def shouldLoadFieldsFile(self, filePath, file=None):
        self.fieldsFileChanged = True
    def shouldLoadSectionsFile(self, filePath, file=None):
        self.sectionsFileChanged = True
    def shouldLoadTournamentsFile(self, filePath, file=None):
        self.tournamentsFileChanged = True
    def shouldLoadLeagueTableFile(self, filePath, file=None):
        leagueId = file[file.find('leagueId')+8:].rstrip('.json')
        if not leagueId.isdigit():
            return
        self.leagueTableFileChanged[leagueId] = True
    def shouldLoadRulesFile(self, filePath, file=None):
        self.rulesFileChanged = True
    def shouldLoadGamesFile(self, filePath, file=None):
        self.gamesFileChanged = True
    def shouldLoadMessagesFile(self, filePath, file=None):
        self.messagesFileChanged = True

    def loadActiveRefereeDetails(self, filePath, path=None, initial=False):
        if initial or self.shouldLoadRefereesFile:
            refereesDetails = self.handleUsers.getAllRefereesDetails()
            localReferees = helpers.load_from_file(filePath)
            if localReferees and len(localReferees) > 0:
                localRefereesDetails = {}
                for refId in localReferees:
                    localRefereesDetails[refId] = refereesDetails[refId]
                refereesDetails = localRefereesDetails            
            activeRefereeDetails = [refereesDetails[refId] for refId in refereesDetails if refereesDetails[refId].get('name') and refereesDetails[refId].get('status') == "active" and str(refId)[-1] in self.refIdsPartition]
            sortedActiveRefereeDetails = sorted(activeRefereeDetails, key=lambda referee: referee['name'])
            activeRefereeDetails = {}
        if initial or self.refTemplatesFileChanged and len(self.refTemplatesFileChanged) > 0:
            self.refTemplateMessages = {}
        for refereeDetail in sortedActiveRefereeDetails:
            refId = refereeDetail['refId']
            if initial or self.shouldLoadRefereesFile:
                activeRefereeDetails[refId] = refereeDetail
            if initial or self.refTemplatesFileChanged.get(refId, False):
                refTemplatedFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/'
                self.loadRefTemplates(refTemplatedFilePath, f'refId{refereeDetail["refId"]}.json')

        if initial or self.shouldLoadRefereesFile:
            self.activeRefereeDetails = activeRefereeDetails
            self.logger.info(f'Referees#: {len(refereesDetails)} Active#: {len(activeRefereeDetails)}')

    def loadRefTemplates(self, filePath, file):
        refId = file[file.find('refId')+5:].rstrip('.json')
        if not refId.isdigit():
            return
        refTemplate = helpers.load_from_file(f'{filePath}{file}')
        self.logger.info(f'refTemplateId={refId}#{len(refTemplate)}')
        self.refTemplateMessages[refId] = refTemplate

    def writeRefTemplate(self, refereeDetail):
        refTemplatedFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/refId{refereeDetail["refId"]}.json'
        templates = self.refTemplateMessages[refereeDetail['refId']]
        helpers.save_to_file(templates, refTemplatedFilePath)
    
    def readRefereeDetails(self, filePath):
        refereeDetails = {}
        try:
            refereesList = helpers.load_from_file(filePath)

            for refId in refereesList:
                refereeDetail = self.handleUsers.getRefereeDetailByRefId(refId)
                refereeDetails[refId] = refereeDetail
            return refereeDetails
        except Exception as ex:
            self.logError('readRefereeDetails', ex, refereeDetail)

        return None
    
    def writeRefereeDetails(self, refereeDetail):
        self.logger.info('write referees...')
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/details/refereesDetails.json'
            refereeDetails = self.readRefereeDetails(referee_file_path)
            refereeDetails[refereeDetail['refId']] = refereeDetail
            helpers.save_to_file(refereeDetails, referee_file_path)
            self.activeRefereeDetails = refereeDetails
        except Exception as ex:
            self.logError('writeReferees', ex, refereeDetail)

    def loadFields(self, filePath, file=None):
        self.logger.info('load fields...')
        self.fields = helpers.load_from_file(filePath)

    def loadSections(self, filePath, file=None):
        self.logger.info('load sections...')
        self.sections = helpers.load_from_file(filePath)

    def loadTournaments(self, filePath, file=None, initial=False):
        self.logger.info('load tournaments...')
        self.tournaments = helpers.load_from_file(filePath)

        self.logger.info('load tournaments tables...')
        self.tournamentsTables = {}
        for tournamentName in self.tournaments:
            tournament = self.tournaments[tournamentName]
            if tournament.get('leagueId'):
                leagueId = str(tournament["leagueId"])
                if initial or self.leagueTableFileChanged.get(leagueId):
                    filePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/'
                    self.loadLeagueTable(filePath, f'leagueId{leagueId}.json')

    def loadLeagueTable(self, filePath, file):
        leagueId = file[file.find('leagueId')+8:].rstrip('.json')
        if not leagueId.isdigit():
            return
        fullPath = f'{filePath}{file}'
        if os.path.exists(fullPath):
            self.tournamentsTables[leagueId] = helpers.load_from_file(fullPath)
            self.logger.info(f'refresh table leagueId={leagueId} #teams={len(self.tournamentsTables[leagueId])}...')

    def loadRules(self, filePath, file=None):
        self.logger.info('load rules...')
        file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/rules.json'
        self.rules = helpers.load_from_file(file_path)

    def loadGames(self, filePath=None, file=None):
        self.logger.info('load games...')
        file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/games.json'
        self.games = helpers.load_from_file(file_path)

    def writeGame(self, gamePk, gameDetail):
        gamesFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/games.json'
        self.games[gamePk] = gameDetail
        helpers.save_to_file(self.games, gamesFilePath)

    def getTagText(self, objType, tag, cellHtml):
        if tag and f'{tag}Tag' in self.dataDic[objType]:
            tagParse = self.dataDic[objType][f'{tag}Tag']
            for filter, useText in tagParse['dic']:
                if filter == None or filter in cellHtml:
                    return tagParse['name'], useText
        
        return None, None

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
            self.logError('convertGamesTableToTextUsingSoup', ex)
            return None

        return results

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
            self.logger.debug(self.colorText(refereeDetail, f'convertGamesTableToText/tablesLocator={cnt}'))
            if cnt == 0: #Still need to investigate this scenario
                return results
            
            if cnt == 1:
                gamesTable = tablesLocator.nth(0)
                rowsLocator = gamesTable.locator('tr')
                cnt = await rowsLocator.count()
                self.logger.debug(self.colorText(refereeDetail, f'convertGamesTableToText/rowsLocator={cnt}'))
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
            self.logError('convertGamesTableToText', ex, refereeDetail)
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
            self.logger.debug(self.colorText(refereeDetail, f'convertReviewsTableToText/tablesLocator={cnt}'))
            if cnt == 0: #Still need to investigate this scenario
                return results
            
            if cnt == 1:
                reviewsTable = tablesLocator.nth(0)
                rowsLocator = reviewsTable.locator('tr')
                cnt = await rowsLocator.count()
                self.logger.debug(self.colorText(refereeDetail, f'convertReviewsTableToText/rowsLocator={cnt}'))
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
            self.logError(f'convertReviewsTableToText', ex, refereeDetail)
            return None
        
        return results
        
    def objProperty(self, obj, property):
        if obj.get(property):
            return f'{property}: {obj.get(property)}'
        return None

    def generateGameRefereeDetails(self, currentGame, job): 
        currentJobProp = currentGame.get('nested').get(job)

        if currentJobProp:
            details = f'\n{job}'
            details += f"\n{self.objProperty(currentJobProp, '* שם')}"
            details += f"\n{self.objProperty(currentJobProp, '* סטטוס')}"
            details += f"\n{self.objProperty(currentJobProp, '* דרג')}"
            details += f"\n{self.objProperty(currentJobProp, '* טלפון')}"
            details += f"\n{self.objProperty(currentJobProp, '* כתובת')}"
            return details
        else:
            return ''
        
    def generateGameDetails(self, game):
        details = ''
        details += self.objProperty(game, 'תאריך')
        details += f"\n{self.objProperty(game, 'יום')}"
        details += f"\n{self.objProperty(game, 'מסגרת משחקים')}"
        details += f"\n{self.objProperty(game, 'משחק')}"
        details += f"\n{self.objProperty(game, 'סבב')}"
        details += f"\n{self.objProperty(game, 'מחזור')}"
        details += f"\n{self.objProperty(game, 'מגרש')}"
        details += f"\n{self.objProperty(game, 'סטטוס')}"
        details += '\n'
        details += self.generateGameReferees(game)
        return details

    def generateGameReferees(self, game):
        details = ''
        details += self.generateGameRefereeDetails(game, 'שופט ראשי')
        details += self.generateGameRefereeDetails(game, 'שופט ראשי*')
        details += self.generateGameRefereeDetails(game, 'ע. שופט 1')
        details += self.generateGameRefereeDetails(game, 'ע. שופט 2')
        details += self.generateGameRefereeDetails(game, 'שופט רביעי')
        details += self.generateGameRefereeDetails(game, 'שופט מזכירות')
        details += self.generateGameRefereeDetails(game, 'שופט ראשון')
        details += self.generateGameRefereeDetails(game, 'שופט שני')
        return details

    def generateReviewDetails(self, game):
        details = ''
        details += self.objProperty(game, 'מס.')
        details += f"\n{self.objProperty(game, 'תאריך')}"
        details += f"\n{self.objProperty(game, 'שעה')}"
        details += f"\n{self.objProperty(game, 'מסגרת משחקים')}"
        details += f"\n{self.objProperty(game, 'משחק')}"
        details += f"\n{self.objProperty(game, 'מגרש')}"
        details += f"\n{self.objProperty(game, 'מחזור')}"
        details += f"\n{self.objProperty(game, 'תפקיד במגרש')}"
        details += f"\n{self.objProperty(game, 'מבקר')}"
        details += f"\n{self.objProperty(game, 'ציון')}"
        return details

    async def parseText(self, objType, convertResults):
        try:
            data = self.dataDic[objType]
            listObjects = []
            obj = None
            nestedList = {}
            nestedObj = {}
            nestedCells = {}

            if convertResults:
                for convertResult in convertResults:
                    header = convertResult.get("header")
                    cell = convertResult.get('cell')
                    line = f'{header+":" if header else ""}{convertResult["text"]}'
                    line = line.strip()
                    if line:
                        idx = line.find(':')
                        if idx > -1:
                            self.logger.debug(f'{idx} {len(line)} {line}')
                            tag = line[:idx].strip()
                            tagValue = line[idx+1:].strip()
                            if tag in data["tags"]:
                                if tag == data["initTag"]:
                                    if obj:
                                        if nestedObj:
                                            nestedPk = nestedObj[data['pkNestedTags']]
                                            if nestedList.get(nestedPk):
                                                nestedList[f'{nestedPk}*'] = nestedObj    
                                            else:
                                                nestedList[nestedPk] = nestedObj
                                        obj['nested'] = nestedList
                                        obj['cells'] = nestedCells
                                        nestedList = {}
                                        nestedObj = {}
                                        nestedCells = {}
                                        listObjects.append(obj)
                                    obj = {}
                                obj[tag] = tagValue
                                nestedCells[header] = cell
                            elif tag in data["nestedTags"]:
                                if tag == data["initNestedTag"]:
                                    if nestedObj:
                                        nestedPk = nestedObj[data['pkNestedTags']]
                                        if nestedList.get(nestedPk):
                                            nestedList[f'{nestedPk}*'] = nestedObj    
                                        else:
                                            nestedList[nestedPk] = nestedObj
                                    nestedObj = {}
                                nestedObj[tag] = tagValue
                                nestedCells[header] = cell

                if nestedObj:
                    nestedPk = nestedObj[data['pkNestedTags']]
                    if nestedList.get(nestedPk):
                        nestedList[f'{nestedPk}*'] = nestedObj    
                    else:
                        nestedList[nestedPk] = nestedObj
                
                if obj:
                    obj['nested'] = nestedList
                    obj['cells'] = nestedCells
                    listObjects.append(obj)

            dicObjects = {}
            for obj in listObjects:
                pk = ''
                for tag in data["pkTags"]:
                    pk += obj[tag]
                dicObjects[pk] = obj
            self.logger.debug(f'n={len(dicObjects)} {dicObjects}')

            return dicObjects

        except Exception as ex:
            self.logError(f'parseText', ex)
            return None

    async def processTemplatesGames(self, objType, refereeData, page):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]

            messages = self.refTemplateMessages[refereeDetail['refId']]
            self.logger.debug(self.colorText(refereeDetail, f"{len(messages)}"))
            if messages:
                save = False
                for msgId in list(messages.keys()):
                    self.logger.debug(self.colorText(refereeDetail, f"{msgId}"))
                    message = messages[msgId]
                    self.logger.debug(self.colorText(refereeDetail, f"{msgId} {message.get('repliedButtonId')} {message['action']}"))
                    if message['created'] < datetime.now() - timedelta(weeks=2):
                        del messages[msgId]
                        save = True
                    if message.get('status') != 'created':
                        continue

                    if message['action'] == 'approveGame':
                        gameId = message['gameId']
                        if not refereeDetail.get(objType) or not refereeDetail[objType].get(gameId):
                            continue
                        game = refereeDetail[objType][gameId]
                        if not game.get('cells') or not game['cells'].get('סטטוס'):
                            continue
                        self.logger.info(self.colorText(refereeDetail, f"{message['msgSid']} gameId={gameId} {game['משחק']}"))
                        cell = game['cells']['סטטוס']
                        result = await handleTournaments.approveGame(refereeDetail, gameId, cell, page)
                        if result:
                            message['status'] = 'completed'
                            message['updated'] = datetime.now()
                            self.logger.info(self.colorText(refereeDetail, f"{gameId} אושר בפורטל"))
                            await self.sendGeneralNotification(refereeDetail, f'משחק {game["משחק"]}', 'השיבוץ אושר בפורטל')
                            save = True
                
                    elif message['action'] == 'forceSend':
                        objType = message['objType']
                        if objType and not refereeDetail.get(objType):
                            continue
                        if not objType or objType == 'games':
                            refereeData['games']['prevList'] = {}
                        if not objType or objType == 'reviews':
                            refereeData['reviews']['prevList'] = {}
                        self.logger.info(self.colorText(refereeDetail, f"{message['msgSid']} objType={objType}"))
                        message['status'] = 'completed'
                        message['updated'] = datetime.now()
                        self.logger.info(self.colorText(refereeDetail, f"{objType} ישלח מחדש"))
                        save = True
                
                if save:
                    self.writeRefTemplate(refereeDetail)

        except Exception as ex:
            self.logError(f'processTemplatesGames', ex, refereeDetail)

    async def postParseGames(self, objType, refereeData, page, manager):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            if not refereeDetail.get(objType): 
                refereeDetail[objType] = {}
            for gamePk in refereeData[objType]['currentList']:
                game = refereeData[objType]['currentList'][gamePk] 
                prevGame = refereeData[objType]['prevList'].get(gamePk) 
                if prevGame:
                    game['id'] = prevGame['id']
                else:
                    game['id'] = str(uuid.uuid4())[:8]
                if not refereeDetail[objType].get(game['id']):
                    refereeDetail[objType][game['id']] = {}
                refereeDetail[objType][game['id']] = game

            if self.dataDic[objType].get('processTemplates'):
                await self.dataDic[objType]['processTemplates'](objType, refereeData, page)

            for gamePk in refereeData[objType]['currentList']:
                game = refereeData[objType]['currentList'][gamePk] 
                prevGame = refereeData[objType]['prevList'].get(gamePk) 
                teamNames = game['משחק']       
                teams = teamNames.split(' - ')
                game['homeTeamName'] = teams[0].strip()
                game['guestTeamName'] = teams[1].strip()
                game['date'] = datetime.strptime(game['תאריך'], "%d/%m/%y %H:%M")
                for nestedObj in game['nested']:
                    if game['nested'][nestedObj]['* שם'] == refereeDetail['name']:
                        game['תפקיד'] = nestedObj
                        break

                if game.get('cells'):
                    del game['cells']

        except Exception as ex:
            self.logError(f'postParseGames', ex, refereeDetail)

    async def postParseReviews(self, objType, refereeData, page, manager):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            numOfReviews = len(refereeData[objType]['currentList'])
            i = 0
            if not refereeDetail.get(objType): 
                refereeDetail[objType] = {}
            for reviewPk in refereeData[objType]['currentList']:
                review = refereeData[objType]['currentList'][reviewPk]
                prevReview = refereeData[objType]['prevList'].get(reviewPk) 
                if prevReview:
                    review['id'] = prevReview['id']
                else:
                    review['id'] = str(uuid.uuid4())[:8]
                if not refereeDetail[objType].get(review['id']):
                    refereeDetail[objType][review['id']] = {}
                refereeDetail[objType][review['id']] = review
                review['מס.'] = f'{numOfReviews-i}'
                review['date'] = datetime.strptime(review['תאריך'], "%d/%m/%y")
                if review.get('cells'):
                    del review['cells']
                i += 1
        except Exception as ex:
            self.logError(f'postParseReviews', ex, refereeDetail)

    async def compareList(self, objType, refereeData, page):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            prevList = refereeData[objType]['prevList']
            currentList = refereeData[objType]['currentList']

            prevItem = None
            currentItem = None

            generateDetailsFunc = self.dataDic[objType]['generate']

            #Added
            added = sorted(list(set(currentList.keys()) - set(prevList.keys())), key=lambda game: currentList[game].get('date'))
            refereeData[objType]['added'] = added
            refereeData[objType]['addedText'] = ''
            for pk in refereeData[objType]['added']:
                currentItem = currentList[pk]
                currentItemText = generateDetailsFunc(currentItem)
                refereeData[objType]['addedText'] += f'{currentItemText}\n'
                if 'reminders' in refereeDetail:
                    if 'reminders' not in currentItem:
                        currentItem['reminders'] = {}
                    i = 0
                    for reminder in refereeDetail['reminders']:
                        if i==0:
                            currentItem['reminders']['firstReminder']={'reminderInHrs':int(reminder), 'sent':False}
                        elif i==1:
                            currentItem['reminders']['lastReminder']={'reminderInHrs':int(reminder), 'sent':False}
                        i+=1

            #Removed
            if 'removeFilter' in self.dataDic[objType]:
                filteredprevList = {}
                for pk in prevList:
                    prevItem = prevList[pk]
                    if prevItem.get('date') >= datetime.now():
                        filteredprevList[pk] = prevItem
            else:
                filteredprevList = prevList

            refereeData[objType]['removed'] = sorted(list(set(filteredprevList.keys()) - set(currentList.keys())), key=lambda game: filteredprevList[game].get('date'))
            refereeData[objType]['removedText'] = ''
            for pk in refereeData[objType]['removed']:
                currentItem = filteredprevList[pk]
                currentItemText = generateDetailsFunc(currentItem)
                refereeData[objType]['removedText'] += f'{currentItemText}\n'
                tournamentName = currentItem['מסגרת משחקים']
                tournament = self.tournaments.get(tournamentName)
                if self.sections.get(tournament['section']):
                    await handleTournaments.refreshLeagueTable(page, tournament, self.sections[tournament['section']])

            #Changed/Nonchanged
            changedList = {}
            nonChangedList = {}
            potentialChangePks = sorted(list(set(prevList.keys()) & set(currentList.keys())), key=lambda game: currentList[game].get('date'))
            for pk in potentialChangePks:
                prevItem = prevList[pk]
                currentItem = currentList[pk]
                prevItemText = generateDetailsFunc(prevItem)
                currentItemText = generateDetailsFunc(currentItem)
                if prevItemText != currentItemText:
                    changedList[pk] = currentItem
                else:
                    nonChangedList[pk] = currentItem

            refereeData[objType]['changed'] = sorted(changedList, key=lambda game: currentList[game].get('date'))
            refereeData[objType]['changedText'] = ''
            for pk in refereeData[objType]['changed']:
                currentItem = changedList[pk]
                currentItemText = generateDetailsFunc(currentItem)
                refereeData[objType]['changedText'] += f'{currentItemText}\n'

        except Exception as ex:
            self.logError(f'compareList', ex, refereeDetail)

    async def findGameTeamsInTable(self, game):
        tournamentName = game['מסגרת משחקים']
        tournament = self.tournaments.get(tournamentName)
        leagueTable = None
        homeTeam = None
        guestTeam = None
        if tournament and tournament['tournament'] == 'league' and self.tournamentsTables.get(f"{tournament['leagueId']}"):
            leagueTable = self.tournamentsTables[f"{tournament['leagueId']}"]
            homeTeam = leagueTable.get(game['homeTeamName'].translate(self.translation_table))
            if not homeTeam:
                homeTeamBestMatch = helpers.find_best_match(game['homeTeamName'], leagueTable.keys())
                if homeTeamBestMatch:
                    homeTeam = leagueTable.get(homeTeamBestMatch.translate(self.translation_table))
            guestTeam = leagueTable.get(game['guestTeamName'].translate(self.translation_table))
            if not guestTeam:
                guestTeamBestMatch = helpers.find_best_match(game['guestTeamName'], leagueTable.keys())
                if guestTeamBestMatch:
                    guestTeam = leagueTable.get(guestTeamBestMatch.translate(self.translation_table))

        return (tournament,leagueTable, homeTeam, guestTeam)

    def teamStatistics(self, teamInTable):
        text = f"\n*{teamInTable['קבוצה']}*:"
        text += f"\nמיקום: {teamInTable['מיקום']}"
        text += f"\nנקודות: {teamInTable['נקודות']}"
        text += f"\nיחס שערים: {teamInTable['שערים']}"
        return text

    async def gameStatistics(self, game, extended=True):
        (tournament, leagueTable, homeTeam, guestTeam) = await self.findGameTeamsInTable(game)
        if tournament and homeTeam and guestTeam:
            homeTeamPosition = int(homeTeam.get('מיקום'))
            guestTeamPosition = int(guestTeam.get('מיקום'))
            homeTeamStatistics = self.teamStatistics(homeTeam)
            aboveHomeTeamStatistics = None
            if homeTeamPosition > 1 and guestTeamPosition != homeTeamPosition - 1:
                aboveHomeTeam = next((team for team in leagueTable.values() if team.get("מיקום") == str(homeTeamPosition-1)), None)
                aboveHomeTeamStatistics = self.teamStatistics(aboveHomeTeam)
            guestTeamStatistics = self.teamStatistics(guestTeam)
            aboveGuestTeamStatistics = None
            if guestTeamPosition > 1 and homeTeamPosition != guestTeamPosition - 1:
                aboveGuestTeam = next((team for team in leagueTable.values() if team.get("מיקום") == str(guestTeamPosition-1)), None)
                aboveGuestTeamStatistics = self.teamStatistics(aboveGuestTeam)

            text = '*נתונים:*'
            text += f'\n{homeTeamStatistics}'
            text += f'\n{guestTeamStatistics}'
            if aboveHomeTeamStatistics:
                text += f'\n{aboveHomeTeamStatistics}'
            if aboveGuestTeamStatistics:
                text += f'\n{aboveGuestTeamStatistics}'
            return text
    
        return None

    async def gamesActions(self, objType, refereeData, page):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            self.logger.debug(self.colorText(refereeDetail, 'reminders'))
            
            games = refereeData[objType]['currentList']
            i = 0
            for gamePk in games:
                i += 1
                game = games[gamePk]

                tournamentName = game['מסגרת משחקים']
                tournament = self.tournaments.get(tournamentName)

                addressDetails = None
                fieldTitle = game.get('מגרש')
                if fieldTitle:
                    addressDetails = self.fields[fieldTitle]['addressDetails']
                self.logger.debug(self.colorText(refereeDetail, f"reminders1 {game.get('date')}"))

                if 'reminders' in refereeDetail:
                    if 'reminders' not in game:
                        game['reminders'] = {}
                    reminders = game['reminders']
                    if 'lineupsAnnounced' not in reminders:
                        reminders['lineupsAnnounced']={'reminderInHrs': 4, 'sent': False}
                    if 'gameReport' not in game['reminders'] and game.get('תפקיד') == 'שופט ראשי':
                        reminders['gameReport']={'reminderInHrs': -3, 'sent': False}
                    
                    for reminder in reminders:
                        reminderInHrs = reminders[reminder]['reminderInHrs']
                        if reminderInHrs == -99:
                            continue

                        if reminders[reminder]['sent'] == False:
                            checkReminderTime = await self.checkReminderTime(game['date'], reminderInHrs, 5)
                            if checkReminderTime:
                                noticeTitle = None
                                noticeDetails = None

                                secondsLeft = round((game['date'] - datetime.now()).total_seconds())
                                minsLeft = round(secondsLeft/60)
                                hoursLeft = round(minsLeft/60)

                                if reminder == 'firstReminder':
                                    noticeTitle = f'תזכורת ראשונה {game["מסגרת משחקים"]}'
                                    noticeDetails = f"בעוד {hoursLeft} שעות יש לך משחק"
                                    if len(game['nested']) > 1:
                                        noticeDetails += f", נא לתאם עם הצוות"
                                    #statistics
                                    statistics = await self.gameStatistics(game, True)
                                    if statistics:
                                        noticeDetails += f'\n{statistics}'
                                elif reminder == 'lastReminder':
                                    noticeTitle = f'תזכורת אחרונה {game["מסגרת משחקים"]}'
                                    noticeDetails = f'בעוד {hoursLeft} שעות מתחיל המשחק נא להערך בהתאם'
                                    #arrival time
                                    if 'addressDetails' in refereeDetail and 'coordinates' in refereeDetail['addressDetails'] and addressDetails:
                                        from_coordinates_lat = refereeDetail['addressDetails']['coordinates']['lat']
                                        from_coordinates_lng = refereeDetail['addressDetails']['coordinates']['lng']
                                        to_coordinates_lat = addressDetails['coordinates']['lat']
                                        to_coordinates_lng = addressDetails['coordinates']['lng']
                                        arriveAt = game['date'] + timedelta(seconds=-refereeDetail["timeArrivalInAdvance"]*60)
                                        duration_secs = await helpers.getWazeRouteDuration(page, from_coordinates_lat, from_coordinates_lng, to_coordinates_lat, to_coordinates_lng, arriveAt)
                                        if duration_secs:
                                            durationStr = helpers.seconds_to_hms(duration_secs)
                                            if durationStr[:3] == '00:':
                                                durationStr = f'{durationStr[3:]} דקות'
                                            else:
                                                durationStr = f'{durationStr} שעות'
                                            departDateTime = arriveAt + timedelta(seconds=-duration_secs)
                                            departTimeStr = departDateTime.strftime("%H:%M")
                                            if departTimeStr:
                                                noticeDetails += f'\n\n*משך הנסיעה:*'
                                                noticeDetails += f'\nכדי להגיע {refereeDetail["timeArrivalInAdvance"]} דקות לפני המשחק הוא {durationStr},'
                                                noticeDetails += f' כדאי לצאת בשעה {departTimeStr}'
                                    #waze link
                                    noticeDetails += f'\n\n*קישור למגרש:* {addressDetails["wazeLink"]}'
                                    #field address
                                    noticeDetails += f'\n\n*כתובת המגרש:* {addressDetails["address"]}'

                                    if tournament and tournament.get('rules'):
                                        rules = self.rules.get(tournament['rules'].strip())
                                        if rules:
                                            noticeDetails += f'\n*חוקים:*'
                                            for rule in rules['game']:
                                                noticeDetails += f"\n{rule}: {rules['game'][rule]}"
                                            if tournament['tournament'] == 'cup':
                                                for rule in rules['cup']:
                                                    noticeDetails += f"\n{rule}: {rules['cup'][rule]}"
                                
                                elif reminder == 'lineupsAnnounced':

                                    if not self.games.get(gamePk):
                                        (tournament, leagueTable, homeTeam, guestTeam) = await self.findGameTeamsInTable(game)
                                        if tournament:
                                            url = await handleTournaments.getGameUrl(page, tournament, game['סבב'], game['מחזור'], homeTeam.get('teamId') if homeTeam else None, guestTeam.get('teamId') if guestTeam else None, game['homeTeamName'], game['guestTeamName'])
                                            if url:
                                                playersSections = await handleTournaments.scrapGameDetails(page, url)
                                                gameDetail = { 'url': url, 'players': playersSections }
                                                self.writeGame(gamePk, gameDetail)
                                                self.loadGames()

                                    if self.games.get(gamePk):
                                        url = self.games[gamePk].get('url')
                                        playersSections = self.games[gamePk].get('players')
                                        noticeTitle = f'פורסמו ההרכבים {game["מסגרת משחקים"]}'
                                        if secondsLeft:
                                            durationStr = helpers.seconds_to_hms(secondsLeft)
                                            if durationStr[:3] == '00:':
                                                durationStr = f'{durationStr[3:]} דקות'
                                            else:
                                                durationStr = f'{durationStr} שעות'
                                            noticeDetails = f'המשחק יתחיל בעוד {durationStr}'
                                        noticeDetails += f"\nלהלן הקישור לפרטי המשחק {url}"

                                        noticeDetails += '\n*קבוצה ביתית:*'
                                        homeActiveNos = ','.join(playersSections[0])
                                        noticeDetails += f'\n*הרכב:* {homeActiveNos}'
                                        if len(playersSections[1]) > 0:
                                            homeBencheNos = ','.join(playersSections[1])
                                            noticeDetails += f'\n*מחליפים:* {homeBencheNos}'
                                        noticeDetails += f'\n*מאמן:* {playersSections[3]}'

                                        noticeDetails += '\n*קבוצה אורחת:*'
                                        guestActiveNos = ','.join(playersSections[4])
                                        noticeDetails += f'\n*הרכב:* {guestActiveNos}'
                                        if len(playersSections[5]) > 0:
                                            guestBenchNos = ','.join(playersSections[5])
                                            noticeDetails += f'\n*מחליפים:* {guestBenchNos}'
                                        noticeDetails += f'\n*מאמן:* {playersSections[7]}'

                                        if False and tournament and tournament.get('rules'):
                                            rules = self.rules.get(tournament['rules'])
                                            if rules:
                                                noticeDetails += f'\n*חוקים:*'
                                                for rule in rules['game']:
                                                    noticeDetails += f"\n{rule}: {rules['game'][rule]}"
                                                if tournament['tournament'] == 'cup':
                                                    for rule in rules['cup']:
                                                        noticeDetails += f"\n{rule}: {rules['cup'][rule]}"
                                elif reminder == 'gameReport':
                                    noticeTitle = f'נא למלא דו״ח בפורטל למשחק {game["מסגרת משחקים"]}:'
                                    noticeDetails = f'{self.loginUrl}'

                                if noticeTitle and noticeDetails:
                                    if game['סטטוס'] == 'מחכה לאישור':
                                        noticeTitle += f" ({game['סטטוס']})"
                                    msgSid = await self.reminder(refereeDetail, game['date'], noticeTitle, game["משחק"], noticeDetails)
                                    reminders[reminder]['sent'] = True
                                    reminders[reminder]['messageSid'] = msgSid
                        i += 1

        except Exception as ex:
            self.logError(f'actions', ex, refereeDetail)

    async def sendGeneralReminders(self, refereeDetail):
        reminderTime = os.environ.get('registerReminderTime')
        if reminderTime == None:
            return
        reminderHour = int(reminderTime[:2])
        reminderMin = int(reminderTime[2:])
        sendReminderContentSid = os.environ.get('twilioOpenWindow')
        sendReminder = False
        now = datetime.now()
        refereeDetail = self.activeRefereeDetails[refereeDetail['refId']]
        lastGeneralReminder = refereeDetail.get('lastGeneralReminder')
        
        next_am = now.replace(hour=reminderHour, minute=reminderMin, second=0, microsecond=0)
        if now >= next_am:
            next_am += timedelta(days=1)
        
        checkReminderTime = await self.checkReminderTime(next_am, 0, 10)
        if checkReminderTime and (not lastGeneralReminder or lastGeneralReminder <  next_am):
            sendReminder = True
            lastGeneralReminder = next_am

        next_pm = now.replace(hour=reminderHour+12, minute=reminderMin, second=0, microsecond=0)
        if now >= next_pm:
            next_pm += timedelta(days=1)

        checkReminderTime = await self.checkReminderTime(next_pm, 0, 10)
        if checkReminderTime and (not lastGeneralReminder or lastGeneralReminder <  next_pm):
            sendReminder = True
            lastGeneralReminder = next_pm

        if sendReminder:
            await self.twilioClient.sendUsingContentTemplate(refereeDetail['mobile'], sendReminderContentSid, {'name': refereeDetail['name']})

        refereeDetail['lastGeneralReminder'] = lastGeneralReminder

    async def checkReminderTime(self, dueDate, hoursInAdvance, reminderOffsetInMins):
        remindBefore1AM = 1
        remindAfter6AM = 6
        reminderInAdvance = hoursInAdvance * 60 * 60
        offset = reminderOffsetInMins * 60
        timeAfteDueDateInMins = 5 * 60
        if hoursInAdvance < 0:
            timeAfteDueDateInMins = 24 * 60
        now = datetime.now()

        if remindBefore1AM < now.hour < remindAfter6AM:
            return False
        
        if False or dueDate - timedelta(seconds=reminderInAdvance + offset) < now < dueDate + timedelta(seconds=timeAfteDueDateInMins * 60):# - timedelta(seconds=reminderInAdvance):
            return True
        
        return False

    async def reminder(self, refereeDetail, dueDate, noticeTitle, gameTitle, noticeDetails):
        msgSid = await self.sendGameNoticeNotification(noticeTitle, gameTitle, noticeDetails, refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
        self.logger.debug(self.colorText(refereeDetail, f'reminders {dueDate}'))
        return msgSid
    
    async def send_push_notification(self, deviceToken, title, body):
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            token=deviceToken,  # The recipient's device token
        )

        try:
            # Send the message
            response = messaging.send(message)
            self.logger.info(f"Successfully sent message: {response}")
        except Exception as ex:
            self.logError(f'sendPush', ex)

    async def sendNewGameNotification(self, title, game, toId, refId, toMobile, toName, toDeviceToken=None, sendAt=None):
        newgame = self.twilioNewGameContentSid      
        gameDumps = helpers.save_to_json(game)
        msgSid = None

        fileId = self.createIcs(refId, game)
        icsFileUrl = f'{self.apiServiceUrlBase}file/{game["id"]}'

        if self.twilioUseFreeText:
            approveUrl = f'{self.apiServiceUrlBase}approveGame/{refId}/{msgSid}'
            message = f"{title}\n{self.dataDic['games']['generate'](game)}"
            message = f'{message}\nניתן לאשר אוטומטית בפורטל דרך הקישור הבא:\n{approveUrl}'
            msgSid = await self.twilioClient.sendFreeText(toMobile=toMobile, message=message, mediaUrl=[icsFileUrl], sendAt=sendAt)

        if self.twilioUseTemplate and newgame:
            variables = {
                'date': f"{game.get('יום')} {game.get('תאריך')}",
                'tournament': game.get('מסגרת משחקים'),
                'game': game.get('משחק'),
                'round': game.get('סבב'),
                'week': game.get('מחזור'),
                'field': game.get('מגרש'),
                'status': game.get('סטטוס'),
                'referees': self.generateGameReferees(game),
                'gameId': game['id'],
                'fileId': fileId
            }
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=newgame, contentVariables=variables, mediaUrl=icsFileUrl, sendAt=sendAt)
        
        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=gameDumps, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=helpers.save_to_json(game))

        return msgSid
    
    async def sendGameUpdateNotification(self, title, game, gameRemoval, toId, refId, toMobile, toName, toDeviceToken=None, sendAt=None):
        gamesupdate = self.twilioGameUpdateContentSid
        msgSid = None

        fileId = self.createIcs(refId, game, gameRemoval)
        icsFileUrl = f'{self.apiServiceUrlBase}file/{game["id"]}'

        if self.twilioUseFreeText:
            message = f"{title}\n{self.dataDic['games']['generate'](game)}"
            msgSid = await self.twilioClient.sendFreeText(toMobile=toMobile, message=message, mediaUrl=icsFileUrl, sendAt=sendAt)
        
        if self.twilioUseTemplate and gamesupdate:
            variables = {
                'title': title,
                'date': f"{game.get('יום')} {game.get('תאריך')}",
                'tournament': game.get('מסגרת משחקים'),
                'game': game.get('משחק'),
                'round': game.get('סבב'),
                'week': game.get('מחזור'),
                'field': game.get('מגרש'),
                'status': game.get('סטטוס'),
                'referees': self.generateGameReferees(game),
                'fileId': fileId
            }
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=gamesupdate, contentVariables=variables, mediaUrl=icsFileUrl, sendAt=sendAt)

        gameDumps = helpers.save_to_json(game)

        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=gameDumps, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=gameDumps)

        return msgSid
    
    async def sendGameNoticeNotification(self, noticeTitle, gameTitle, noticeDetails, refId, toMobile, toName, toDeviceToken=None, sendAt=None):
        gamenotice = self.twilioGameNoticeContentSid

        msgSid = None
        noticeDetails1 = noticeDetails.replace('"','\"')
        variables = {
            'noticeTitle': noticeTitle,
            'gameTitle': gameTitle,
            'noticeDetails': noticeDetails1
        }

        if self.twilioUseFreeText:
            msgSid = await self.twilioClient.sendFreeText(toMobile=toMobile, message=f'{noticeTitle}\n{gameTitle}\n{noticeDetails1}', sendAt=sendAt)
        
        if self.twilioUseTemplate and gamenotice:
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=gamenotice, contentVariables=variables, sendAt=sendAt)

        return msgSid

    async def sendNewReviewNotification(self, title, review, toId, refId, toMobile, toName, toDeviceToken=None, sendAt=None):
        newreview = os.environ.get('twilioNewReviewContentSid')
        msgSid = None

        if self.twilioUseFreeText or not (self.twilioUseTemplate and newreview):
            message = f"{title}\n{self.dataDic['reviews']['generate'](review)}"
            msgSid = await self.twilioClient.sendFreeText(toMobile=toMobile, message=message, sendAt=sendAt)

        if self.twilioUseTemplate and newreview:
            variables = {
                'date': f"{review.get('תאריך')} {review.get('שעה')}",
                'tournament': review.get('מסגרת משחקים'),
                'game': review.get('משחק'),
                'field': review.get('מגרש'),
                'week': review.get('מחזור'),
                'jobTitle': review.get('תפקיד במגרש'),
                'reviewer': review.get('מבקר'),
                'grade': review.get('ציון')
            }
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=newreview, contentVariables=variables, sendAt=sendAt)

        reviewDumps = helpers.save_to_json(review)

        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=reviewDumps, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=reviewDumps)

        return msgSid

    async def sendReviewUpdateNotification(self, title, review, reviewRemoval, toId, refId, toMobile, toName, toDeviceToken=None, sendAt=None):
        reviewsupdate = os.environ.get('twilioReviewUpdateContentSid')
        msgSid = None

        if self.twilioUseFreeText or not (self.twilioUseTemplate and reviewsupdate):
            message = f"{title}\n{self.dataDic['reviews']['generate'](review)}"
            msgSid = await self.twilioClient.sendFreeText(toMobile=toMobile, message=message, sendAt=sendAt)

        if self.twilioUseTemplate and reviewsupdate:
            variables = {
                'action': title,
                'date': f"{review.get('תאריך')} {review.get('שעה')}",
                'tournament': review.get('מסגרת משחקים'),
                'game': review.get('משחק'),
                'field': review.get('מגרש'),
                'week': review.get('מחזור'),
                'jobTitle': review.get('תפקיד במגרש'),
                'reviewer': review.get('מבקר'),
                'grade': review.get('ציון')
            }
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=reviewsupdate, contentVariables=variables, sendAt=sendAt)

        reviewDumps = helpers.save_to_json(review)

        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=reviewDumps, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=reviewDumps)

        return msgSid

    async def sendGeneralNotification(self, refereeDetail, noticeTitle, noticeDetails, sendAt=None):
        msgSid = None

        noticeDetails1 = noticeDetails.replace('"','\"')
        if True or self.twilioUseFreeText:
            msgSid = await self.twilioClient.sendFreeText(toMobile=refereeDetail['mobile'], message=f'{noticeTitle}\n{noticeDetails1}', sendAt=sendAt)

        return msgSid

    async def sendFreeTextNotification(self, title, message, toId, toMobile, toName, toDeviceToken=None, sendAt=None):
        msgSid = None
        message1 = message.replace('"','\"')

        msgSid = await self.twilioClient.sendFreeText(toMobile=toMobile, message=f'**{title}**\n{message1}', sendAt=sendAt)

        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=message1, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=message1)

        return msgSid

    async def notifyUpdate(self, objType, refereeData):
        try:
            msgSid = None
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            title = self.dataDic[objType]["notifyTitle"]
            itemDescFunc = self.dataDic[objType]['generate']

            if len(refereeData[objType]['removed']) > 0:
                title1 = f"שיבוץ נמחק"
                if objType == 'reviews':
                    title1 = 'ביקורת נמחקה'
                for pk in refereeData[objType]['removed']:
                    item = refereeData[objType]['prevList'][pk]
                    itemDesc = itemDescFunc(item)
                    self.logger.info(self.colorText(refereeDetail, f'\n{title1}\n{itemDesc}'))
                    if objType == 'games':
                        msgSid = await self.sendGameUpdateNotification(title1, item, True, refereeDetail["id"], refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
                    elif objType == 'reviews':
                        msgSid = await self.sendReviewUpdateNotification(title1, item, True, refereeDetail["id"], refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
                    item['removeMessageSid'] = msgSid
                self.logger.debug(self.colorText(refereeDetail, f"{objType} removed list#{len(refereeData[objType]['removed'])}={refereeData[objType]['removed']}"))

            if len(refereeData[objType]['changed']) > 0:
                title1 = f"עדכון שיבוץ"
                if objType == 'reviews':
                    title1 = 'עדכון ביקורת'
                for pk in refereeData[objType]['changed']:
                    item = refereeData[objType]['currentList'][pk]
                    itemDesc = itemDescFunc(item)
                    self.logger.info(self.colorText(refereeDetail, f'\n{title1}\n{itemDesc}'))
                    if objType == 'games':
                        msgSid = await self.sendGameUpdateNotification(title1, item, False, refereeDetail["id"], refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
                    elif objType == 'reviews':
                        msgSid = await self.sendReviewUpdateNotification(title1, item, False, refereeDetail["id"], refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
                    item['changedMessageSid'] = msgSid
                self.logger.debug(self.colorText(refereeDetail, f"{objType} changed list#{len(refereeData[objType]['changed'])}={refereeData[objType]['changed']}"))

            if len(refereeData[objType]['added']) > 0:
                title1 = title + f"*חדש*\n{refereeData[objType]['addedText']}\n"
                for pk in refereeData[objType]['added']:
                    item = refereeData[objType]['currentList'][pk]
                    itemDesc = itemDescFunc(item)
                    self.logger.info(self.colorText(refereeDetail, f'\n{itemDesc}'))
                    if objType == 'games':
                        msgSid = await self.sendNewGameNotification(title, item, refereeDetail["id"], refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
                    elif objType == 'reviews':
                        msgSid = await self.sendNewReviewNotification(title, item, refereeDetail["id"], refereeDetail["refId"], refereeDetail["mobile"], refereeDetail["name"])
                    item['newMessageSid'] = msgSid
                self.logger.debug(self.colorText(refereeDetail, f"{objType} added list#{len(refereeData[objType]['added'])}={refereeData[objType]['added']}")) 

            self.logger.debug(self.colorText(refereeDetail, f'notify: {objType}'))
        
        except Exception as ex:
            self.logError(f'notifyUpdate', ex, refereeDetail)

    def getRefereeFilePath(self, objType, refereeDetail):
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/{objType}/'
            referee_file_path = f'{referee_file_path}refId{refereeDetail["refId"]}_{self.fileVersion}'

            return referee_file_path
        except Exception as e:
            pass

    async def readRefereeDataFile(self, objType, refereeData):
        refereeDetail = self.activeRefereeDetails[refereeData['refId']]
        if objType not in refereeData or 'currentList' not in refereeData[objType] or not refereeData[objType]['currentList']:
            file_datetime = None
            
            try:
                referee_file_path = f'{self.getRefereeFilePath(objType, refereeDetail)}.json'
                self.logger.debug(f'file: {referee_file_path}')
                if objType not in refereeData:
                    refereeData[objType] = {}
                t=0
                while not os.path.exists(referee_file_path) and t < 5:
                    await asyncio.sleep(150 * (t + 1) / 1000)
                    t += 1

                if os.path.exists(referee_file_path):
                    file_datetime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                    refereeData[objType]['currentList'] = helpers.load_from_file(referee_file_path)
                else:
                    file_datetime = datetime.now()
                    refereeData[objType]['currentList'] = {}
                refereeData[objType]['fileDateTime'] = helpers.datetime_to_str(file_datetime)
            except Exception as ex:
                self.logError(f'readRefereeDataFile', ex, refereeDetail)

    async def writeRefereeDataFile(self, objType, refereeData):
        try:
            prevListText = helpers.save_to_json(refereeData[objType]['prevList'])
            currentListText = helpers.save_to_json(refereeData[objType]['currentList'])
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            pref_referee_file_path = self.getRefereeFilePath(objType, refereeDetail)
            referee_file_path = f'{pref_referee_file_path}.json' 
            dir = os.path.dirname(referee_file_path)
            self.logger.debug(f'file: {dir} {referee_file_path}')
            if dir and not os.path.exists(dir):
                self.logger.debug(f'create dir: {dir}')
                os.makedirs(dir)
            fileExists = os.path.exists(referee_file_path)
            if prevListText != currentListText or not fileExists:
                self.logger.debug(f'prev:{prevListText}')
                self.logger.debug(f'current:{currentListText}')
                if fileExists:
                    fileDateTime = helpers.datetime_to_str(datetime.fromtimestamp(os.path.getmtime(referee_file_path)))
                    shutil.copy(referee_file_path, f'{pref_referee_file_path}_{fileDateTime}.json')
                helpers.save_to_file(refereeData[objType]['currentList'], referee_file_path)
                refereeData[objType]['fileDateTime'] = helpers.datetime_to_str(datetime.now())
        except Exception as ex:
            self.logError(f'writeFileText', ex, refereeDetail)

    def resetProgress(self):
        self.completedReferees = 0

    def simulateDynamicProgress(self, infoNoResult):
        self.completedReferees += 1
        elaspsedTime = helpers.stopwatchElapsed(f'Loop time')
        progress = f"\rProgress: [{'#' * self.completedReferees}{'.' * (self.activeReferees - self.completedReferees)}] {self.completedReferees}/{self.activeReferees} {elaspsedTime}"
        sys.stdout.write(progress)
        sys.stdout.flush()
        if infoNoResult or self.completedReferees == self.activeReferees:
            print()

    async def checkRefereeTask(self, manager, refId):
        anyChange = False
        semaphore, page = await manager.acquire_page()
        refereeDetail = self.activeRefereeDetails[refId]
        self.logger.debug(self.colorText(refereeDetail, f'seq={refereeDetail.get("seq")}'))
        
        try:          
            testResult = helpers.testConnection(self.IFAUrl, 443)
            if testResult:
                self.logger.warning(f'TestConnection: {testResult}')

            refereeData = { 'refId': refId }

            await self.sendGeneralReminders(refereeDetail)

            (windowIsOpen, lastMessageDatetime) = self.twilioClient.checkIfWindowIsOpen(refereeDetail['mobile'])
            if windowIsOpen == False:
                self.logger.warning(self.colorText(refereeDetail,f'24 hours window is closed, last message time {lastMessageDatetime}'))
                #return

            loginSuccesful = await self.login(refereeDetail, page)
            self.logger.debug(self.colorText(refereeDetail, f'after login = {loginSuccesful}'))

            if loginSuccesful == False:
                await manager.release_page(semaphore, page)
                return

            for objType in refereeDetail.get('objTypes'):
                await self.readRefereeDataFile(objType, refereeData)

            for objType in refereeDetail.get('objTypes'):
                if objType == 'games' and self.checkGames or objType == 'reviews' and self.checkReviews:
                    changed = await self.checkRefereeData(objType, refereeData, page, manager)
                    if changed:
                        anyChange = True

        except Exception as ex:
            self.logError(f'CheckRefereeTask', ex, refereeDetail)

        try:
            if self.alwaysRenewPages:
                await manager.release_page(semaphore, page)
            else:
                loggedoutSuccessfully = await self.logout(refereeDetail, page)
                self.logger.debug(self.colorText(refereeDetail, f'loggedoutSuccessfully={loggedoutSuccessfully}'))
                if loggedoutSuccessfully == True:
                        await manager.release_page(semaphore, page)
                else:
                    self.logger.warning(self.colorText(refereeDetail, f'renew page'))
                    await manager.renew_page(semaphore, page)
            #await manager.context.tracing.stop(path=f"{referee_file_path}traceFinally{datetime.now().strftime("%Y%m%d%H%M%S")}}.zip")
        except Exception as ex:
            self.logError(f'CheckRefereeTask loggedOut', ex, refereeDetail)
        finally:
            #self.simulateDynamicProgress(infoNoResult)
            return anyChange

    async def checkRefereeData(self, objType, refereeData, page, manager):
        changed = False
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            self.logger.info(self.colorText(refereeDetail, f'Checking {objType}...'))
            
            swName = f'checkRefereeData={refereeDetail["name"]}{objType}'
            helpers.stopwatchStart(swName)

            found = False
            parsedList = None
            
            for i in range(2):
                if i > 0:
                    await helpers.gotoUrl(page, 'about:blank')
                    title = await page.title()
                    pass
                helpers.stopwatchStart(f'{swName}Url')
                await helpers.gotoUrl(page, self.dataDic[objType]['url'])
                #await page.wait_for_load_state(state='load', timeout=5000)
                helpers.stopwatchStop(f'{swName}Url', level=self.swLevel)

                cnt = 0
                retries = 3
                for j in range(retries):
                    t = i * retries + j + 1
                    #self.logger.warning(f'{i} {j} {t}')
                    helpers.stopwatchStart(f'{swName}Read')
                    await asyncio.sleep(150 * (j + 1) / 1000)
                    self.logger.debug(f'url={page.url}')
                    title = await page.title()
                    self.logger.debug(self.colorText(refereeDetail, f'title: {title}'))
                    
                    helpers.stopwatchStart(f'{swName}Convert')
                    convertResults = await self.dataDic[objType]['convert'](page, refereeDetail)
                    self.logger.debug(self.colorText(refereeDetail, f'convertResults: {convertResults}'))
                    helpers.stopwatchStop(f'{swName}Convert', level=self.swLevel)

                    if convertResults == None:
                        break
                    
                    else:
                        if len(convertResults) == 0:
                            if not refereeData[objType].get('NoResult'):
                                refereeData[objType]['NoResult'] = 0
                            refereeData[objType]['NoResult'] += 1
                            self.logger.debug(self.colorText(refereeDetail, f"{objType} no results found = {refereeData[objType]['NoResult']}"))                            

                        if self.dataDic[objType].get('parse'):
                            helpers.stopwatchStart(f'{swName}parse')
                            parsedList = await self.dataDic[objType]['parse'](objType, convertResults)
                            self.logger.debug(self.colorText(refereeDetail, f'parsedList: {parsedList}'))
                            helpers.stopwatchStop(f'{swName}parse', level=self.swLevel)

                            if parsedList and len(parsedList) > 0:
                                found = True
                                cnt = len(parsedList)

                        elif "parse" not in self.dataDic[objType]:# and len(hText) > len(refereeData[objType][f"prevText"]):
                            found = True

                        self.logger.debug(self.colorText(refereeDetail, f'parse objType={objType} t={t} found={found} parsedList={cnt}'))
            
                        if found == True:
                            break

                if found == True:
                    break

            if parsedList == None:
                self.logger.warning(self.colorText(refereeDetail, f"{objType} no results found = {refereeData[objType]['NoResult']}"))
                del refereeData[objType]['NoResult']
                return
            
            refereeData[objType]['prevList'] = refereeData[objType]['currentList']
            refereeData[objType]['currentList'] = parsedList

            # copy additional properties from prev to current
            if refereeData[objType]['prevList']:
                for pk in refereeData[objType]['currentList']:
                    item = refereeData[objType]['currentList'][pk]                    
                    prevItem = refereeData[objType]['prevList'].get(pk)
                    if prevItem:
                        for key in prevItem:
                            if key not in item:
                                item[key] = copy.deepcopy(prevItem[key])

            if parsedList != None:
                if self.dataDic[objType].get('postParse'):
                    await self.dataDic[objType]['postParse'](objType, refereeData, page, manager)

                if self.dataDic[objType].get('compare'):
                    await self.dataDic[objType]['compare'](objType, refereeData, page)

                    # avoid errors in reviews and send removal for all reviews
                    if (len(refereeData[objType]['removed']) > 1 and len(refereeData[objType]['changed']) >= 0) and len(refereeData[objType]['added']) == 0:
                        self.logger.error(self.colorText(refereeDetail,f"CheckRefereeData removed={len(refereeData[objType]['removed'])} changed={len(refereeData[objType]['changed'])} {refereeData[objType]}"))
                        return
                    if objType == 'games' and len(refereeData[objType]['added']) > 0:
                        self.lastGameAssignment = datetime.now()
                    if len(refereeData[objType]['added']) > 0 or len(refereeData[objType]['removed']) > 0 or len(refereeData[objType]['changed']) > 0:
                        self.logger.info(self.colorText(refereeDetail, f"{objType} A:{len(refereeData[objType]['added'])} R:{len(refereeData[objType]['removed'])} C:{len(refereeData[objType]['changed'])} #{cnt}/{t}"))
                        await self.dataDic[objType]['notify'](objType, refereeData)
                        changed = True
                    else:
                        fileDateText = refereeData[objType]['fileDateTime']
                        self.logger.info(self.colorText(refereeDetail, f'No {objType} update since {fileDateText} #{cnt}/{t}'))
            
                if refereeData[objType].get('currentList') and self.dataDic[objType].get('actions'):
                    await self.dataDic[objType]['actions'](objType, refereeData, page)

                await self.writeRefereeDataFile(objType, refereeData)

            helpers.stopwatchStop(f'{swName}', level=self.swLevel)
        except Exception as ex:
            self.logError('CheckRefereeData', ex, refereeDetail)
        finally:
            return changed

    def colorText(self, refereeDetail, text):
        color = Fore.WHITE
        try:
            if refereeDetail.get('color'):
                color = eval(f"Fore.{refereeDetail['color']}")
        except Exception as ex:
            pass
        return f'{color}{refereeDetail["name"]}#{refereeDetail["refId"]}:{text}{Style.RESET_ALL}'

    async def login(self, refereeDetail, page):
        try:
            t=0
            while page.url != self.gamesUrl and t < 5:
                t+=1
                self.logger.debug(self.colorText(refereeDetail, f'login#{t}'))
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
                    self.logError('login', ex, refereeDetail)
            await asyncio.sleep(500 / 1000)

            if page.url != self.gamesUrl:
                self.logger.error(self.colorText(refereeDetail, f'Login failed#{t}'))
            else:
                self.logger.debug(self.colorText(refereeDetail, f'Login successfull#{t}'))
                return True

        except Exception as ex:
            self.logError(f'Login', ex, refereeDetail)

        return False
    
    async def logout(self, refereeDetail, page):
        t=0
        
        while page.url != self.loginUrl and t < 3:
            try:
                t+=1
                await helpers.gotoUrl(page, self.loginUrl)
                self.logger.debug(self.colorText(refereeDetail, f'logout#{t}'))
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
            self.logger.error(self.colorText(refereeDetail, f'Logout failed#{t}'))
            return False
        else:
            self.logger.debug(self.colorText(refereeDetail, f'Logout successfull#{t}'))
    
        return True

    async def start(self):
        self.logger.debug('Start')

        await self.mqttClient.publish(topic=self.mqttTopic, title="RefPortal Start", payload=self.openText)

        try:
            async with async_playwright() as p:                
                i = 0
                browser = None
                manager = pageManager.PageManager(self.concurrentPages)
                while True:
                    try:
                        if self.activeRefereeDetails:
                            if i % self.browserRenewal == 0:
                                self.logger.info('Browser renewal...')
                                if browser:# and context:
                                    await browser.close()
                                browser = await p.firefox.launch(headless=eval(os.environ.get('browserHeadless') or 'True'), args=['--disable-dev-shm-usage','--disable-extensions','--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-software-rasterizer','--verbose'])
                                #context = await browser.new_context()
                                #p.debug = 'pw:browser,pw:page'
                                #await context.tracing.start(screenshots=True, snapshots=True)
                                await manager.initialize_pages(browser)

                            helpers.stopwatchStart(f'Loop time')
                            self.resetProgress()
                            refereesTasks = [self.checkRefereeTask(manager, refId) for refId in self.activeRefereeDetails]
                            tasksResults = await asyncio.gather(*refereesTasks)
                            for taskResult in tasksResults:
                                pass
                            helpers.stopwatchStop(f'Loop time', level='info')
                            self.logger.info(f'last Game Assignment={self.lastGameAssignment}')
                            self.loadMetadata()
                            i += 1
                    except Exception as ex:
                        self.logError('Start', ex)
                    finally:
                        await asyncio.sleep(self.pollingInterval / 1000)

        except Exception as ex:
            self.logError(f'start', ex)
        
        finally:
            self.logger.debug(f'close')
            if self.refereeFileWatchObserver:
                self.refereeFileWatchObserver.stop()
            if self.fieldsFileWatchObserver:
                self.fieldsFileWatchObserver.stop()
            if self.sectionsFileWatchObserver:
                self.sectionsFileWatchObserver.stop()
            if self.tournamentsFileWatchObserver:
                self.tournamentsFileWatchObserver.stop()
            if self.rulesFileWatchObserver:
                self.rulesFileWatchObserver.stop()
            if self.gamesFileWatchObserver:
                self.gamesFileWatchObserver.stop()
            if self.messagesFileWatchObserver:
                self.messagesFileWatchObserver.stop()
            if browser:# and context:
                await browser.close()
            # Disconnect the client
            self.mqttClient.disconnect()

    def logError(self, label, ex, refereeDetail=None):
        if refereeDetail:
            self.logger.error(self.colorText(refereeDetail, f'{label}: Exception Type: {type(ex).__name__}, Message: {ex}'))
        else:
            self.logger.error(f'{label}: Exception Type: {type(ex).__name__}, Message: {ex}')
        logging.exception("An error occurred")

    async def getSpecificGame(self):
        refereeData = {}
        refereeData['refId'] = '43679'
        await self.readRefereeDataFile('games', refereeData)
        for gamePk in refereeData['games']['currentList']:
            game = refereeData['games']['currentList'][gamePk]
            stat = await self.gameStatistics(game, extended=True)
            pass

    async def testTwillio(self, refId, toMobile, title, message, contentSid, sendAt=None):
        game = {
            "id": "adhdsfj",
            "תאריך": "20/01/25 19:30",
            "יום": "שני",
            "מסגרת משחקים": "ליגת ילדים ב' דן",
            "משחק": "מכבי הרצליה - עירוני מודיעין",
            "סבב": "1",
            "מחזור": "10",
            "מגרש": "הרצליה רן 2 (ילדים וטרומים)",
            "סטטוס": "מאושר",
            "nested" : {
                "שופט ראשי": {
                    "תפקיד": "שופט ראשי",
                    "* שם": "שחר גיא",
                    "* סטטוס": "מאשר",
                    "* דרג": "דרג אזורי-טרומים",
                    "* טלפון": "0547799979",
                    "* כתובת": "אהרון גולדשטיין 2 גבעתיים"
                }
            }
        }
        await self.sendNewGameNotification('שיבוץ חדש', game, None, refId, toMobile, 'גיא', toDeviceToken=None, sendAt=None)

def fixTournaments():
    tournaments_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/tournaments.json'
    tournaments = helpers.load_from_file(tournaments_file_path)
    for t in tournaments:
        tournament = tournaments[t]
        for k in tournament.keys():
            value = tournament[k]
            if isinstance(value, str):
                tournament[k] = value.strip()
    helpers.save_to_file(tournaments, f'{tournaments_file_path}_new')

if __name__ == "__main__":
    app = None
    try:
        #fixTournaments()
        #exit
        print("Hello RefPortalllll")
        refPortalService = RefPortalService()
        refPortalService.logger.info(f'Main run')
        asyncio.run(refPortalService.start())
        #asyncio.run(refPortalService.testTwillio('43679', '+972547799979', 'This is a title', 'יואב שחר', 'HX5b361717a06dc26fa2ad8f3a75545efe'))
        pass
    except Exception as ex:
        print(f'Main Error: {ex}')
        pass