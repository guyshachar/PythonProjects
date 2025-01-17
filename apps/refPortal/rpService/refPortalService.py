#from Shared.logger import Logger
import logging
from datetime import datetime
from datetime import timedelta
import os
import uuid
import sys
from pathlib import Path
import socket
import shutil
import asyncio
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
from fileWatcher import watchFileChange

class RefPortalService():
    def __init__(self):
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        self.fileVersion = os.environ.get('fileVersion') or 'v'
        self.openText=f'Ref Portal Service {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        self.logger.info(self.openText)

        self.swDic = {}
        self.loginUrl = os.environ.get('loginUrl') or 'https://ref.football.org.il/login'
        self.gamesUrl = os.environ.get('gamesUrl') or 'https://ref.football.org.il/referee/home'
        self.reviewsUrl = os.environ.get('reviewsUrl') or 'https://ref.football.org.il/referee/reviews'
        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "read": self.readPortalGames,
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
                "pkTags": [ "מסגרת משחקים", "משחק" ],
                "nestedTags": [ "תפקיד", "* שם", "* סטטוס", "* דרג", "* טלפון", "* כתובת" ],
                "pkNestedTags": "תפקיד",
                "initNestedTag" : 'תפקיד',
                "סטטוסTag": { "name": "סטטוס", "dic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")] },
                "* שםTag": { "name": "* סטטוס", "dic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")] },
                'removeFilter': 'תאריך'
           },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "read": self.readPortalReviews,
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

        self.pollingInterval = int(os.environ.get('loadInterval') or '10000')
        self.alwaysClosePage = eval(os.environ.get('alwaysClosePage') or 'True')
        self.checkGames = eval(os.environ.get('checkGames') or 'True')
        self.checkReviews = eval(os.environ.get('checkReviews') or 'True')
        self.translation_table = str.maketrans('', '', "!@#'? \"")

        self.swLevel = os.environ.get('swLevel') or 'debug'

        twilioServiceId = os.environ.get('twilioServiceId')
        self.twilioClient = TwilioClient(twilioServiceId=twilioServiceId)
        self.twilioSend = eval(os.environ.get('twilioSend') or 'False')
        self.handleUsers = HandleUsers()

        self.watchFiles()

        self.concurrentPages = int(os.environ.get('concurrentPages') or '4')
        self.browserRenewal = int(os.environ.get('browserRenewal') or '5')
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
        self.logger.info(f'logLevel={logLevel} url={self.loginUrl} interval={self.pollingInterval} twilio={self.twilioSend} mqtt={self.mqttPublish} pages={self.concurrentPages}')
   
    async def readPortalGames(self, page):
        try:
            result = None
            self.logger.debug(f'before readPortalGames')

            tables = await page.query_selector_all('table.ng-tns-c150-1')
            if len(tables) == 1:
                result = tables[0]

        except Exception as ex:
            self.logger.error(f'readPortal error: {ex}')

        finally:        
            self.logger.debug(f'after readPortalGames')
            return result

    def updateRefereeAddress(self, refereeDetail, address = None):
        if 'addressDetails' not in refereeDetail or address and address != refereeDetail['addressDetails']['address']:
            refereeDetail['addressDetails'] = { 'address': address, 'coordinates': None}

        if refereeDetail['addressDetails']['address'] and not refereeDetail['addressDetails']['coordinates']:
            coordinates, formattedAddress, error = helpers.get_coordinates_google_maps(refereeDetail['addressDetails']['address'])
            lat, lng = coordinates
            refereeDetail['addressDetails']['coordinates'] = { "lat": lat, "lng": lng}
            refereeDetail['addressDetails']['formattedAddress'] = formattedAddress
            self.writeRefereeDetails(refereeDetail)

    def watchFiles(self):
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}referees/details/referees.json'
            self.refereeFileWatchObserver = watchFileChange(referee_file_path, self.loadActiveRefereeDetails)

            fields_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}fields/fields.json'
            self.fieldsFileWatchObserver = watchFileChange(fields_file_path, self.loadFields)

            sections_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/sections.json'
            self.sectionsFileWatchObserver = watchFileChange(sections_file_path, self.loadSections)

            tournaments_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/tournaments.json'
            self.tournamentsFileWatchObserver = watchFileChange(tournaments_file_path, self.loadTournaments)

            rules_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/rules.json'
            self.rulesFileWatchObserver = watchFileChange(rules_file_path, self.loadRules)

            self.loadActiveRefereeDetails(referee_file_path)
            self.loadFields(fields_file_path)
            self.loadSections(sections_file_path)
            self.loadTournaments(tournaments_file_path)
            self.loadRules(rules_file_path)

        except Exception as ex:
            self.logger.error(f'watchFiles error: {ex}')

    def loadActiveRefereeDetails(self, filePath, path=None):
        refereesDetails = self.handleUsers.getAllRefereesDetails()
        localReferees = helpers.load_from_file(filePath)
        if localReferees:
            localRefereesDetails = {}
            for refId in localReferees:
                localRefereesDetails[refId] = refereesDetails[refId]
            refereesDetails = localRefereesDetails
        activeRefereeDetails = [refereesDetails[refId] for refId in refereesDetails if refereesDetails[refId].get('name') and refereesDetails[refId].get('status') == "active"]
        sortedActiveRefereeDetails = sorted(activeRefereeDetails, key=lambda referee: referee['name'])
        activeRefereeDetails = {}
        for refereeDetail in sortedActiveRefereeDetails:
            activeRefereeDetails[refereeDetail['refId']] = refereeDetail
        self.activeRefereeDetails = activeRefereeDetails
        self.logger.info(f'Referees#: {len(refereesDetails)} Active#: {len(activeRefereeDetails)}')

    def readRefereeDetails2(self, filePath):
        refereeDetails = {}
        try:
            refereeDetails = helpers.load_from_file(filePath)
            return refereeDetails
        except Exception as ex:
            self.logger.error(f'readRefereeDetails error: {ex}')

        return None
    
    def readRefereeDetails(self, filePath):
        refereeDetails = {}
        try:
            refereesList = helpers.load_from_file(filePath)

            for refId in refereesList:
                refereeDetail = self.handleUsers.getRefereeDetail(refId)
                refereeDetails[refId] = refereeDetail
            return refereeDetails
        except Exception as ex:
            self.logger.error(f'readRefereeDetails error: {ex}')

        return None
    
    def writeRefereeDetails(self, refereeDetail):
        self.logger.info('load referees...')
        try:
            referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/details/refereesDetails.json'
            refereeDetails = self.readRefereeDetails(referee_file_path)
            refereeDetails[refereeDetail['refId']] = refereeDetail
            helpers.save_to_file(refereeDetails, referee_file_path)
            self.activeRefereeDetails = refereeDetails
        except Exception as ex:
            self.logger.error(f'writeReferees error: {ex}')

    def loadFields(self, filePath, file=None):
        self.logger.info('load fields...')
        self.fields = helpers.load_from_file(filePath)

    def loadSections(self, filePath, file=None):
        self.logger.info('load sections...')
        self.sections = helpers.load_from_file(filePath)

    def loadTournaments(self, filePath, file=None):
        self.logger.info('load tournaments...')
        self.tournaments = helpers.load_from_file(filePath)

        self.logger.info('load tournaments tables...')
        self.tournamentsTables = {}
        filePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/'
        self.tournamentsFileWatchObserver = watchFileChange(filePath, self.loadLeagueTable)
        for tournamentName in self.tournaments:
            tournament = self.tournaments[tournamentName]
            if tournament.get('leagueId'):
                filePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/'
                self.loadLeagueTable(filePath, f'leagueId{tournament["leagueId"]}.json')

    def loadLeagueTable(self, filePath, file):
        leagueId = file[file.find('leagueId')+8:].strip('.json')
        fullPath = f'{filePath}{file}'
        if os.path.exists(fullPath):
            self.tournamentsTables[leagueId] = helpers.load_from_file(fullPath)
            self.logger.info(f'refresh table leagueId={leagueId} #teams={len(self.tournamentsTables[leagueId])}...')

    def loadRules(self, filePath, file=None):
        self.logger.info('load rules...')
        file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/rules.json'
        self.rules = helpers.load_from_file(file_path)
    
    async def readPortalReviews(self, page):
        result = None
        try:
            self.logger.debug(f'before readPortalReviews')
            table_elements = await page.query_selector_all('table')
            if len(table_elements) > 0:
                result = table_elements[0]

        except Exception as ex:
            self.logger.error(f'readPortal error: {ex}')

        finally:        
            return result

    def getTagText(self, objType, tag, cell):
        if tag and f'{tag}Tag' in self.dataDic[objType]:
            tagParse = self.dataDic[objType][f'{tag}Tag']
            for filter, useText in tagParse['dic']:
                if filter == None or filter in str(cell):
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
        
    async def convertGamesTableToText(self, html):
        games = "games"
        result = []
        statusImages = {}

        try:
            if html == None:
                result.append(f"אין שיבוצים")
                return result

            # Parse the HTML using BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            h = html2text.HTML2Text()
            # Ignore converting links from HTML
            h.ignore_links = False

            # Extract table rows
            rows = soup.find_all('tr')

            # Get headers (assumes the first row contains headers)
            headers = [th.get_text(strip=True) for th in rows[0].find_all('th')]

            # Process each subsequent row and map to headers
            if len(rows) <= 1:
                result.append(f"אין שיבוצים")
            else:
                i = 0
                for row in rows[1:]:  # Skip the header row
                    i += 1
                    cells = row.find_all('td')
                    if len(cells) == len(headers):  # Regular rows
                        for header, cell in zip(headers, cells):
                            cellText = cell.get_text(strip=True)
                            (tagName, tagText) = self.getTagText(games, header, cell)
                            if header and (cellText or tagText):
                                result.append(f"{header}: {cellText or tagText}")
                            if tagName and cellText and tagText:
                                result.append(f"{tagName}: {tagText}")

                            statusImage = cell.find('img', src=lambda x: x and ('15.svg' in x or '16.svg' in x or '17.svg' in x))
                            if statusImage:
                                statusImages[i] = statusImage

                    elif len(cells) == 1:  # Row with colspan
                        html1 = self.transformHtmlTable(str(cells[0]))
                        #self.logger.warning(str(html1))
                        (nestedResult, statusImage_) = await self.convertGamesTableToText(html1)
                        result.append('')
                        result.append(nestedResult)
                        #self.logger.warning(h.handle(cells[0].decode_contents()))
                        #cellText = self.getTagText(games, header, cells[0], h.handle(cells[0].decode_contents()))
                        #result.append(cellText)
                
        except Exception as e:
            self.logger.error(f'convertGamesTableToText {e}')

        finally:
            return ("\n".join(result), statusImages)

    async def convertReviewsTableToText(self, html):
        # Parse the HTML using BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')

        h = html2text.HTML2Text()
        # Ignore converting links from HTML
        h.ignore_links = True

        # Extract table rows
        rows = soup.find_all('tr')

        # Get headers (assumes the first row contains headers)
        headers = [th.get_text(strip=True) for th in rows[0].find_all('th')]

        # Process each subsequent row and map to headers
        result = []
        if len(rows)==1:
            result.append(f"אין ביקורות")
        else:
            for row in rows[1:]:  # Skip the header row
                cells = row.find_all('td')
                if len(cells) == len(headers):  # Regular rows
                    for header, cell in zip(headers, cells):
                        cellText = cell.get_text(strip=True)
                        if header or cellText:
                            result.append(f"{header}: {cellText}")
                    result.append("")
                elif len(cells) == 1:  # Row with colspan
                    result.append(h.handle(cells[0].decode_contents()))

        return ("\n".join(result), None)

    def objProperty(self, obj, property):
        if obj.get(property):
            return f'{property}: {obj.get(property)}'
        return None

    def generateGameRefereeDetails(self, currentGame, job): 
        currentJobProp = currentGame.get('nested').get(job)
        #currentJobPropDumps = json.dumps(currentJobProp)

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
        
    def generateGameDetails(self, game, refereeData):
        details = ''
        details += self.objProperty(game, 'תאריך')
        details += f"\n{self.objProperty(game, 'יום')}"
        details += f"\n{self.objProperty(game, 'מסגרת משחקים')}"
        details += f"\n{self.objProperty(game, 'משחק')}"
        details += f"\n{self.objProperty(game, 'סבב')}"
        details += f"\n{self.objProperty(game, 'מחזור')}"
        details += f"\n{self.objProperty(game, 'מגרש')}"
        details += f"\n{self.objProperty(game, 'סטטוס')}"
        details += self.generateGameRefereeDetails(game, 'שופט ראשי')
        details += self.generateGameRefereeDetails(game, 'שופט ראשי*')
        details += self.generateGameRefereeDetails(game,'ע. שופט 1')
        details += self.generateGameRefereeDetails(game,'ע. שופט 2')
        details += self.generateGameRefereeDetails(game,'שופט רביעי')
        details += self.generateGameRefereeDetails(game,'שופט מזכירות')
        details += self.generateGameRefereeDetails(game,'שופט ראשון')
        details += self.generateGameRefereeDetails(game,'שופט שני')
        return details

    def generateReviewDetails(self, game, refereeData):
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

    async def parseText(self, objType, text):
        try:
            data = self.dataDic[objType]
            listObjects = []
            obj = None
            nestedList = {}
            nestedObj = {}

            if text:
                lines = text.split('\n')
                for line in lines:
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
                                        nestedList = {}
                                        nestedObj = {}
                                        listObjects.append(obj)
                                    obj = {}
                                obj[tag] = tagValue
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

                if nestedObj:
                    nestedPk = nestedObj[data['pkNestedTags']]
                    if nestedList.get(nestedPk):
                        nestedList[f'{nestedPk}*'] = nestedObj    
                    else:
                        nestedList[nestedPk] = nestedObj
                
                if obj:
                    obj['nested'] = nestedList
                    listObjects.append(obj)

            dicObjects = {}
            for obj in listObjects:
                pk = ''
                for tag in data["pkTags"]:
                    pk += obj[tag]
                dicObjects[pk] = obj
            self.logger.debug(f'n={len(dicObjects)} {dicObjects}')

            return dicObjects

        except Exception as e:
            self.logger.error(f'parseText: {e}')
            return None

    async def postParseGames(self, objType, refereeData, page):
        refereeDetail = self.activeRefereeDetails[refereeData['refId']]
        for gamePk in refereeData[objType]['currentList']:
            game = refereeData[objType]['currentList'][gamePk] 
            teamNames = game['משחק']       
            teams = teamNames.split(' - ')
            game['homeTeamName'] = teams[0].strip()
            game['guestTeamName'] = teams[1].strip()
            game['date'] = datetime.strptime(game['תאריך'], "%d/%m/%y %H:%M")
            for nestedObj in game['nested']:
                if game['nested'][nestedObj]['* שם'] == refereeDetail['name']:
                    game['תפקיד'] = nestedObj
                    break

            (tournament, leagueTable, homeTeam, guestTeam) = await self.findGameTeamsInTable(game)
            if tournament and not game.get('url'):
                url = await handleTournaments.getGameUrl(page, tournament, homeTeam.get('teamId') if homeTeam else None, guestTeam.get('teamId') if guestTeam else None, game['homeTeamName'], game['guestTeamName'])
                if url:
                    game['url'] = url
    
    async def postParseReviews(self, objType, refereeData, page):
        numOfReviews = len(refereeData[objType]['currentList'])
        i = 0
        for reviewPk in refereeData[objType]['currentList']:
            review = refereeData[objType]['currentList'][reviewPk]
            review['מס.'] = f'{numOfReviews-i}'
            review['date'] = datetime.strptime(review['תאריך'], "%d/%m/%y")
            i += 1

    async def compareList(self, objType, refereeData, page):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            prevList = refereeData[objType]['prevList']
            currentList = refereeData[objType]['currentList']

            prevItem = None
            currentItem = None

            generateDetails = self.dataDic[objType].get('generate')

            #Added
            added = sorted(list(set(currentList.keys()) - set(prevList.keys())), key=lambda game: currentList[game].get('date'))
            refereeData[objType]['added'] = added
            refereeData[objType]['addedText'] = ''
            for pk in refereeData[objType]['added']:
                currentItem = currentList[pk]
                currentItem['id'] = str(uuid.uuid4())[:8]
                currentItemText = generateDetails(currentItem, refereeData)
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
                currentItemText = generateDetails(currentItem, refereeData)
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
                prevItemText = generateDetails(prevItem, refereeData)
                currentItemText = generateDetails(currentItem, refereeData)
                if prevItemText != currentItemText:
                    changedList[pk] = currentItem
                else:
                    nonChangedList[pk] = currentItem

            refereeData[objType]['changed'] = sorted(changedList, key=lambda game: currentList[game].get('date'))
            refereeData[objType]['changedText'] = ''
            for pk in refereeData[objType]['changed']:
                currentItem = changedList[pk]
                currentItemText = generateDetails(currentItem, refereeData)
                refereeData[objType]['changedText'] += f'{currentItemText}\n'

        except Exception as e:
            self.logger.error(f'compareList: {e}')

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
            if aboveHomeTeamStatistics:
                text += f'\n{aboveHomeTeamStatistics}'
            text += f'\n{guestTeamStatistics}'
            if aboveGuestTeamStatistics:
                text += f'\n{aboveGuestTeamStatistics}'
            return text
    
        return None

    async def gamesActions(self, objType, refereeData, page, approveImages):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            self.logger.debug(self.colorText(refereeDetail, 'reminders'))
            
            games = refereeData[objType]['currentList']
            i = 0
            for pk in games:
                i += 1
                game = games[pk]
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
                    
                    if False: #for testing
                        reminders[0]['reminderInHrs'] = 80
                        reminders[1]['reminderInHrs'] = 80
                        reminders[2]['reminderInHrs'] = 80
                    
                    for reminder in reminders:
                        reminderInHrs = reminders[reminder]['reminderInHrs']
                        if reminderInHrs == -99:
                            continue

                        if reminders[reminder]['sent'] == False:
                            checkReminderTime = await self.checkReminderTime(game['date'], reminderInHrs, 5)
                            if checkReminderTime:
                                title = None
                                message = None

                                secondsLeft = round((game['date'] - datetime.now()).total_seconds())
                                minsLeft = round(secondsLeft/60)
                                hoursLeft = round(minsLeft/60)

                                if reminder == 'firstReminder':
                                    title = f'תזכורת ראשונה למשחק {game["מסגרת משחקים"]}:'
                                    message = f"בעוד {hoursLeft} שעות יש לך משחק"
                                    if len(game['nested']) > 1:
                                        message += f", {game['משחק']} נא לתאם עם הצוות"
                                    #statistics
                                    statistics = await self.gameStatistics(game, True)
                                    if statistics:
                                        message += f'\n{statistics}'
                                elif reminder == 'lastReminder':
                                    title = f'תזכורת אחרונה למשחק {game["מסגרת משחקים"]}:'
                                    message = f'בעוד {hoursLeft} שעות מתחיל המשחק {game["משחק"]} נא להערך בהתאם'
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
                                                message += f'\n\n*משך הנסיעה:*'
                                                message += f'\nכדי להגיע {refereeDetail["timeArrivalInAdvance"]} דקות לפני המשחק הוא {durationStr},'
                                                message += f' כדאי לצאת בשעה {departTimeStr}'
                                    #waze link
                                    message += f'\n\n*קישור למגרש:* {addressDetails["wazeLink"]}'
                                    #field address
                                    message += f'\n\n*כתובת המגרש:* {addressDetails["address"]}'
                                elif reminder == 'lineupsAnnounced':
                                    if game.get('url'):
                                        playersSections = await handleTournaments.scrapGameDetails(page, game['url'])
                                        game['players'] = playersSections
                                        title = f'פורסמו ההרכבים למשחק {game["משחק"]}:'
                                        if secondsLeft:
                                            durationStr = helpers.seconds_to_hms(secondsLeft)
                                            if durationStr[:3] == '00:':
                                                durationStr = f'{durationStr[3:]} דקות'
                                            else:
                                                durationStr = f'{durationStr} שעות'
                                            message = f'המשחק יתחיל בעוד {durationStr}'
                                        message += f"\nלהלן הקישור לפרטי המשחק {game['url']}"

                                        message += '\n*קבוצה ביתית:*'
                                        homeActiveNos = ','.join(playersSections[0])
                                        message += f'\n*הרכב:* {homeActiveNos}'
                                        if len(playersSections[1]) > 0:
                                            homeBencheNos = ','.join(playersSections[1])
                                            message += f'\n*מחליפים:* {homeBencheNos}'
                                        message += f'\n*מאמן:* {playersSections[3]}'

                                        message += '\n*קבוצה אורחת:*'
                                        guestActiveNos = ','.join(playersSections[4])
                                        message += f'\n*הרכב:* {guestActiveNos}'
                                        if len(playersSections[5]) > 0:
                                            guestBenchNos = ','.join(playersSections[5])
                                            message += f'\n*מחליפים:* {guestBenchNos}'
                                        message += f'\n*מאמן:* {playersSections[7]}'

                                        tournamentName = game['מסגרת משחקים']
                                        tournament = self.tournaments.get(tournamentName)
                                        if tournament and tournament.get('rules'):
                                            rules = self.rules.get(tournament['rules'])
                                            if rules:
                                                message += f'\n*חוקים:*'
                                                for rule in rules['game']:
                                                    message += f"\n{rule}: {rules['game'][rule]}"
                                                if tournament['tournament'] == 'cup':
                                                    for rule in rules['cup']:
                                                        message += f"\n{rule}: {rules['cup'][rule]}"
                                elif reminder == 'gameReport':
                                    title = f'נא למלא דו״ח למשחק {game["משחק"]} בפורטל:'
                                    message = f'{self.loginUrl}'

                                if title and message:
                                    if game['סטטוס'] == 'מחכה לאישור':
                                        title += f" ({game['סטטוס']})"
                                    await self.reminder(refereeDetail, game['date'], title, message)
                                    reminders[reminder]['sent'] = True
                        i += 1

                if game.get('askToApproveGame') == True:
                    approveImage = approveImages[i]
                    handleTournaments.approveGame(page, approveImage)
                    game['askToApproveGame'] = False

        except Exception as e:
            self.logger.error(f'actions: {len(games)} {e}')

    async def check24HoursWindow(self, refereeData):
        now = datetime.now()
        refereeDetail = self.activeRefereeDetails[refereeData['refId']]
        windowStartDatetime = refereeDetail.get('windowStartDatetime')
        if not windowStartDatetime or windowStartDatetime + timedelta(seconds=60*60*23) < datetime.now():
            self.sendStart24HoursWindowNotification(refereeDetail['refId'], refereeDetail['mobile'], refereeDetail['name'])

    async def sendGeneralReminders(self, refereeData):
        await self.check24HoursWindow(refereeData)
        return
    
        now = datetime.now()
        refereeDetail = self.activeRefereeDetails[refereeData['refId']]
        lastGeneralReminder = refereeDetail.get('lastGeneralReminder')
        
        next_10am = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= next_10am:
            next_10am += timedelta(days=1)
        
        checkReminderTime = await self.checkReminderTime(next_10am, 0, 10)
        if checkReminderTime and (not lastGeneralReminder or lastGeneralReminder <  next_10am):
            lastGeneralReminder = next_10am
            await self.reminder(refereeDetail, next_10am, 
                                f'תזכורת חידוש רישום',
                                f'https://api.whatsapp.com/send/?phone=%2B14155238886&text=join+of-wheel&type=phone_number&app_absent=0')

        next_10pm = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= next_10pm:
            next_10pm += timedelta(days=1)

        checkReminderTime = await self.checkReminderTime(next_10pm, 0, 10)
        if checkReminderTime and (not lastGeneralReminder or lastGeneralReminder <  next_10pm):
            lastGeneralReminder = next_10pm
            await self.reminder(refereeDetail, next_10pm, 
                                f'תזכורת חידוש רישום',
                                f'https://api.whatsapp.com/send/?phone=%2B14155238886&text=join+of-wheel&type=phone_number&app_absent=0')

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

    async def reminder(self, refereeDetail, dueDate, title, message):
        await self.sendFreeTextNotification(title, message, refereeDetail["id"], refereeDetail["mobile"], refereeDetail["name"])
        self.logger.debug(self.colorText(refereeDetail, f'reminders {dueDate}'))

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
        except Exception as e:
            self.logger.error(f"Error sending message: {e}")

    async def sendStart24HoursWindowNotification(self, refId, toMobile, toName, sendAt=None):
        start24hrswindow = 'HXf896921dba6371e9e99400d523895a67'

        if self.twilioSend:
            sentWhatsappMessage = await self.twilioClient.sendUsingContentTemplate(refId=refId, toMobile=toMobile, contentSid=start24hrswindow, params={'name':f'{toName}'}, sendAt=sendAt)
            await self.handleUsers.start24HoursWindow(self, refId, datetime.now())


    async def sendNewGameNotification(self, title, message, toId, refId, toMobile, toName, toDeviceToken=None, sendAt=None):
        newgameapprovereject = 'HXf896921dba6371e9e99400d523895a67'
        message1 = message
        message1 = message1.replace('"','\"')

        if self.twilioSend:
            sentWhatsappMessage = await self.twilioClient.sendUsingContentTemplate(refId=refId, toMobile=toMobile, contentSid=newgameapprovereject, params={'txt':f'**{title}**\n{message1}'}, sendAt=sendAt)

        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=message1, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=message1)

    async def sendFreeTextNotification(self, title, message, toId, toMobile, toName, toDeviceToken=None, sendAt=None):
        message1 = message
        message1 = message1.replace('"','\"')

        if self.twilioSend:
            sentWhatsappMessage = await self.twilioClient.sendFreeText(toMobile=toMobile, message=f'**{title}**\n{message1}', sendAt=sendAt)

        if self.mqttPublish:
            await self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=message1, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=message1)

    async def notifyUpdate(self, objType, refereeData):
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            message = ''
            if len(refereeData[objType]['added']) > 0:
                message += f"*חדש*\n{refereeData[objType]['addedText']}\n"
                self.logger.debug(self.colorText(refereeDetail, f"{objType} added list#{len(refereeData[objType]['added'])}={refereeData[objType]['added']}")) 

            if len(refereeData[objType]['removed']) > 0:
                message += f"*נמחק*\n~{refereeData[objType]['removedText']}~\n"
                self.logger.debug(self.colorText(refereeDetail, f"{objType} removed list#{len(refereeData[objType]['removed'])}={refereeData[objType]['removed']}"))

            if len(refereeData[objType]['changed']) > 0:
                message += f"*עדכון*\n{refereeData[objType]['changedText']}\n"
                self.logger.debug(self.colorText(refereeDetail, f"{objType} changed list#{len(refereeData[objType]['changed'])}={refereeData[objType]['changed']}"))

            if len(refereeData[objType]['added']) > 0:
                message += f'{self.loginUrl}'

            self.logger.info(self.colorText(refereeDetail, f'notify: {objType}: {message}'))
        
            title = self.dataDic[objType]["notifyTitle"]
            await self.sendFreeTextNotification(title, message, refereeDetail["id"], refereeDetail["mobile"], refereeDetail["name"], len(refereeData[objType]['added']))
        except Exception as e:
            self.logger.error(f'notifyUpdate: {e}')

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
                while not os.path.exists(referee_file_path) and t < 10:
                    await asyncio.sleep(150 * (t + 1) / 1000)
                    t += 1

                if os.path.exists(referee_file_path):
                    file_datetime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                    refereeData[objType]['currentList'] = helpers.load_from_file(referee_file_path)
                else:
                    file_datetime = datetime.now()
                    refereeData[objType]['currentList'] = {}
                if 'prevList' not in refereeData[objType]:
                    refereeData[objType]['prevList'] = {}
                refereeData[objType]['fileDateTime'] = file_datetime.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                self.logger.error(f'readRefereeFile {e}')

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
                    fileDateTime = datetime.fromtimestamp(os.path.getmtime(referee_file_path)).strftime("%Y%m%d%H%M%S")
                    shutil.copy(referee_file_path, f'{pref_referee_file_path}_{fileDateTime}.json')
                helpers.save_to_file(refereeData[objType]['currentList'], referee_file_path)
                refereeData[objType]['fileDateTime'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            self.logger.error(f'writeFileText: {e}')

    def resetProgress(self):
        self.completedReferees = 0

    def simulateDynamicProgress(self, infoNoResult):
        self.completedReferees += 1
        elaspsedTime = helpers.stopwatchElapsed(self, f'Loop time')
        progress = f"\rProgress: [{'#' * self.completedReferees}{'.' * (self.activeReferees - self.completedReferees)}] {self.completedReferees}/{self.activeReferees} {elaspsedTime}"
        sys.stdout.write(progress)
        sys.stdout.flush()
        if infoNoResult or self.completedReferees == self.activeReferees:
            print()

    async def checkRefereeTask(self, manager, refId, infoNoResult):
        anyChange = False
        semaphore, page = await manager.acquire_page()
        refereeDetail = self.activeRefereeDetails[refId]
        self.logger.debug(self.colorText(refereeDetail, f'seq={refereeDetail.get("seq")}'))
        
        try:
            refereeData = { "refId": refId }
            await self.sendGeneralReminders(refereeData)

            loginSuccesful = await self.login(refereeDetail, page)
            self.logger.debug(self.colorText(refereeDetail, f'after login = {loginSuccesful}'))

            if loginSuccesful == False:
                await manager.renew_page(semaphore, page)
                return

            for objType in refereeDetail.get('objTypes'):
                await self.readRefereeDataFile(objType, refereeData)

            if refereeDetail.get('forceSend') == True:
                refereeDetail['forceSend'] = False
                for objType in refereeDetail.get('objTypes'):
                    refereeData[objType]['currentList'] = {}
                self.writeRefereeDetails(refereeDetail)

            for objType in refereeDetail.get('objTypes'):
                changed = await self.checkRefereeData(objType, refereeData, page, infoNoResult)
                if changed:
                    anyChange = True

        except Exception as ex:
            self.logger.error(f'CheckRefereeTask error: {ex}')

        try:
            loggedoutSuccessfully = await self.logout(refereeDetail, page)
            self.logger.debug(self.colorText(refereeDetail, f'loggedoutSuccessfully={loggedoutSuccessfully}'))
            if loggedoutSuccessfully == True:
                manager.release_page(semaphore, page)
            else:
                await manager.renew_page(semaphore, page)
            #await manager.context.tracing.stop(path=f"{referee_file_path}traceFinally{datetime.now().strftime("%Y%m%d%H%M%S")}}.zip")
        except Exception as ex:
            self.logger.error(f'CheckRefereeTask logout error: {ex}')
        finally:
            #self.simulateDynamicProgress(infoNoResult)
            return anyChange

    async def checkRefereeData(self, objType, refereeData, page, infoNoResult):
        changed = False
        try:
            refereeDetail = self.activeRefereeDetails[refereeData['refId']]
            swName = f'checkRefereeData={refereeDetail["name"]}{objType}'
            helpers.stopwatchStart(self, swName)

            found = False
            hText = None
            parsedList = None
            approveImages = {}
            
            for i in range(2):
                helpers.stopwatchStart(self, f'{swName}Url')
                await page.goto(self.dataDic[objType]["url"])
                await page.wait_for_load_state(state='load', timeout=5000)
                helpers.stopwatchStop(self, f'{swName}Url', level=self.swLevel)

                cnt = 0
                for j in range(5):
                    t = i * 5 + j + 1
                    #self.logger.warning(f'{i} {j} {t}')
                    helpers.stopwatchStart(self, f'{swName}Read')
                    await asyncio.sleep(150 * (j + 1) / 1000)
                    self.logger.debug(f'url={page.url}')
                    result = await self.dataDic[objType]["read"](page)
                    title = await page.title()
                    self.logger.debug(self.colorText(refereeDetail, f'title: {title}'))
                    table_outer_html = None
                    if result:
                        table_outer_html = await result.evaluate("element => element.outerHTML")
                    helpers.stopwatchStop(self, f'{swName}Read', level=self.swLevel)
                    #self.logger.warning(f'table_outer_html: {objType} {table_outer_html}')
                    helpers.stopwatchStart(self, f'{swName}Convert')
                    (hText, approveImages) = await self.dataDic[objType]['convert'](table_outer_html)
                    hText = hText.strip()
                    #self.logger.warning(hText)
                    helpers.stopwatchStop(self, f'{swName}Convert', level=self.swLevel)

                    if hText:
                        if self.dataDic[objType].get('parse'):
                            helpers.stopwatchStart(self, f'{swName}parse')
                            parsedList = await self.dataDic[objType]["parse"](objType, hText)
                            helpers.stopwatchStop(self, f'{swName}parse', level=self.swLevel)

                            if parsedList and len(parsedList) > 0:
                                found = True
                                cnt = len(parsedList)

                        elif "parse" not in self.dataDic[objType] and len(hText) > len(refereeData[objType][f"prevText"]):
                            found = True

                        self.logger.debug(self.colorText(refereeDetail, f'parse objType={objType} t={t} found={found} parsedList={cnt}'))
            
                        if found == True:
                            break

                if found == True or refereeData[objType].get('prevList') and len(refereeData[objType]['prevList']) == 0:
                    break

            if parsedList or \
                    not parsedList and not refereeData[objType]['currentList'] or \
                    refereeData[objType].get('NoResult') and refereeData[objType]['NoResult'] > 1:
                if refereeData[objType].get('NoResult'):
                    del refereeData[objType]['NoResult']
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

                if hText:
                    if self.dataDic[objType].get('postParse'):
                        await self.dataDic[objType]['postParse'](objType, refereeData, page)

                    if self.dataDic[objType].get('compare'):
                        await self.dataDic[objType]['compare'](objType, refereeData, page)
                                            
                        if len(refereeData[objType]['added']) > 0 or len(refereeData[objType]['removed']) > 0 or len(refereeData[objType]['changed']) > 0:
                            if not infoNoResult:
                                self.logger.info('\n')
                            self.logger.info(self.colorText(refereeDetail, f"{objType} A:{len(refereeData[objType]['added'])} R:{len(refereeData[objType]['removed'])} C:{len(refereeData[objType]['changed'])} #{cnt}/{t}"))
                            await self.dataDic[objType]['notify'](objType, refereeData)
                            changed = True
                        elif infoNoResult == True:
                            fileDateText = refereeData[objType]['fileDateTime']
                            self.logger.info(self.colorText(refereeDetail, f'No {objType} update since {fileDateText} #{cnt}/{t}'))
                
                    if refereeData[objType].get('currentList') and self.dataDic[objType].get('actions'):
                        await self.dataDic[objType]['actions'](objType, refereeData, page, approveImages)

                    await self.writeRefereeDataFile(objType, refereeData)

            else:
                if not refereeData[objType].get('NoResult'):
                    refereeData[objType]['NoResult'] = 0
                refereeData[objType]['NoResult'] += 1
                if infoNoResult == True:
                    self.logger.warning(self.colorText(refereeDetail, f"{objType} no results found = {refereeData[objType]['NoResult']}"))

            helpers.stopwatchStop(self, f'{swName}', level=self.swLevel)
        except Exception as ex:
            self.logger.error(f'CheckRefereeData error: {ex}')
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
            while page.url != self.gamesUrl and t < 10:
                t+=1
                self.logger.debug(self.colorText(refereeDetail, f'login#{t}'))
                try:
                    await page.goto(self.loginUrl, timeout = 5000)
                    await asyncio.sleep(1000*t / 1000)

                    input_elements = await page.query_selector_all('input')
                    if len(input_elements) == 3:
                        usernameField = input_elements[0]
                        await usernameField.fill(refereeDetail["refId"])

                        passwordField = input_elements[1]
                        await passwordField.fill(self.handleUsers.decryptPassword(refereeDetail['password']))

                        idField = input_elements[2]
                        await idField.fill(refereeDetail["id"])

                        # Find the submit button and click it
                        button_elements = await page.query_selector_all('button')
                        mainButton = button_elements[0]
                        await mainButton.click()  # Replace selector as needed
                        await asyncio.sleep(1000 / 1000)
                except Exception as e:
                    pass
            await asyncio.sleep(1000 / 1000)

            if page.url != self.gamesUrl:
                self.logger.error(self.colorText(refereeDetail, f'Login failed#{t}'))
            else:
                self.logger.debug(self.colorText(refereeDetail, f'Login successfull#{t}'))
                return True

        except Exception as ex:
            self.logger.error(f'Login error: {ex}')

        return False
    
    async def logout(self, refereeDetail, page):
        try:
            t=0
            while page.url != self.loginUrl and t < 10:
                t+=1
                self.logger.debug(self.colorText(refereeDetail, f'logout#{t}'))
                button_elements = await page.query_selector_all("button")
                logoutButtons = [button for button in button_elements if (await button.inner_text()).strip() == "יציאה"]

                self.logger.debug(f'logoutButtons={len(logoutButtons)}')
                if len(logoutButtons) == 1:
                    logoutButton = button_elements[0]
                    await logoutButton.click()
                await asyncio.sleep(1000*t / 1000)

            if page.url != self.loginUrl:
                self.logger.error(self.colorText(refereeDetail, f'Logout failed#{t}'))
            else:
                self.logger.debug(self.colorText(refereeDetail, f'Logout successfull#{t}'))

        except Exception as ex:
            self.logger.error(f'logout error: {ex}')
            return False
    
        return True
    
    async def approveGame(self, refereeDetail, page, i):
        self.logger.debug(self.colorText(refereeDetail, f'approve'))
        try:
            img_elements = await page.query_selector_all("img.ng-tns-c150-1")

            self.logger.debug(f'img_elements={len(img_elements)}')
            approveImg = img_elements[i]
            await approveImg.click()
            await asyncio.sleep(500 / 1000)

        except Exception as ex:
            self.logger.error(f'logout error: {ex}')

    async def start(self):
        self.logger.debug('Start')

        await self.mqttClient.publish(topic=self.mqttTopic, title="RefPortal Start", payload=self.openText)

        try:
            async with async_playwright() as p:                
                i = 0
                browser = None
                manager = pageManager.PageManager(self.concurrentPages)
                infoNoResult = True
                while True:
                    try:
                        if i % self.browserRenewal == 0:
                            self.logger.info('Browser renewal...')
                            if browser:# and context:
                                await browser.close()
                            browser = await p.firefox.launch(headless=True, args=['--disable-dev-shm-usage','--disable-extensions','--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-software-rasterizer','--verbose'])
                            #context = await browser.new_context()
                            #p.debug = 'pw:browser,pw:page'
                            #await context.tracing.start(screenshots=True, snapshots=True)
                            await manager.initialize_pages(browser)

                        helpers.stopwatchStart(self, f'Loop time')
                        self.resetProgress()
                        refereesTasks = [self.checkRefereeTask(manager, refId, infoNoResult) for refId in self.activeRefereeDetails]
                        tasksResults = await asyncio.gather(*refereesTasks)
                        infoNoResult = False or True
                        for taskResult in tasksResults:
                            if taskResult == True:
                                infoNoResult = True
                                break
                        helpers.stopwatchStop(self, f'Loop time', level='info')
                        i += 1
                    except Exception as ex:
                        self.logger.error(f'Start error: {ex}')
                    finally:
                        await asyncio.sleep(self.pollingInterval / 1000)

        except Exception as ex:
            self.logger.error(f'Error: {ex}')
        
        finally:
            self.logger.debug(f'close')
            self.refereeFileWatchObserver.stop()
            self.fieldsFileWatchObserver.stop()
            self.sectionsFileWatchObserver.stop()
            self.tournamentsFileWatchObserver.stop()
            self.rulesFileWatchObserver.stop()
            if browser:# and context:
                await browser.close()
            # Disconnect the client
            self.mqttClient.disconnect()

    async def getSpecificGame(self):
        refereeData = {}
        refereeData['refId'] = '43679'
        await self.readRefereeDataFile('games', refereeData)
        for gamePk in refereeData['games']['currentList']:
            game = refereeData['games']['currentList'][gamePk]
            stat = await self.gameStatistics(game, extended=True)
            pass

    async def testTwillio(self, toMobile, title, message, sendAt=None):
        sentWhatsappMessage = await self.twilioClient.sendFreeText(toMobile=toMobile, message=f'**{title}**\n{message}', sendAt=sendAt)
        print(sentWhatsappMessage)

if __name__ == "__main__":
    app = None
    try:
        print("Hello RefPortalllll")
        refPortalService = RefPortalService()
        refPortalService.logger.info(f'Main run')
        #asyncio.run(refPortalService.start())
        asyncio.run(refPortalService.testTwillio('+972547799979', 'This is a title', 'and a message body'))
        pass
    except Exception as ex:
        print(f'Main Error: {ex}')
        pass