#from Shared.logger import Logger
import logging
#import time
from datetime import datetime
from datetime import timedelta
import time
import json
import os
import socket
import shutil
import asyncio
#from html2image import Html2Image
from bs4 import BeautifulSoup
import html2text
import re
import firebase_admin
from firebase_admin import credentials, messaging
import helpers
import pageManager
import mqttClient
import twilioClient
from playwright.async_api import async_playwright
from enum import Enum
from colorama import Fore, Style

class RefPortalApp():
    def __init__(self):
        #Logger(self)   
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'INFO'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        self.fileVersion = 'v2'
        self.openText=f'Ref Portal {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        self.logger.info(self.openText)

        self.swDic = {}
        self.loginUrl = os.environ.get('loginUrl') or 'https://ref.football.org.il/login'
        self.gamesUrl = os.environ.get('gamesUrl') or 'https://ref.football.org.il/referee/home'
        self.reviewsUrl = os.environ.get('reviewsUrl') or 'https://ref.football.org.il/referee/reviews'
        self.dataDic = {
            "pk" : "pk",
            "objText": "objText",
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "read": self.readPortalGames,
                "convert": self.convertGamesTableToText,
                "parse": self.parseText,
                "compare": self.compareList,
                "actions": self.gamesActions,
                "notify": self.notifyUpdate,
                "notifyTitle" : "שיבוצים:",
                "tags" : [ "תאריך", "יום", "מסגרת משחקים", "משחק", "סבב", "מחזור", "מגרש", "סטטוס",
                           "תפקיד", "* שם", "* דרג", "* טלפון", "* כתובת" ],
                "initTag" : "תאריך",
                "סטטוסTagDic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")],
                "* שםTagDic": [('class="approved"', "מאשר"), ('class="reject"', "לא מאשר"), ('', "טרם אושר")],
                "pkTags": ["מסגרת משחקים", "משחק"],
                "removeFilter": "תאריך"
           },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "read": self.readPortalReviews,
                "convert": self.convertReviewsTableToText,
                "parse": self.parseText,
                "compare": self.compareList,
                "notify": self.notifyUpdate,
                "notifyTitle" : "ביקורות:",
                "tags" : [ "מס.", "תאריך", "שעה", "מסגרת משחקים", "משחק", "מגרש", "מחזור", "תפקיד במגרש", "מבקר", "ציון" ],
                "initTag" : "מס.",
                "excludeCompareTags" : [ "מס." ],
                "pkTags": ["מסגרת משחקים", "משחק"]
            }
        }

        self.pollingInterval = int(os.environ.get('loadInterval') or '10000')
        self.alwaysClosePage = eval(os.environ.get('alwaysClosePage') or 'True')
        self.checkGames = eval(os.environ.get('checkGames') or 'True')
        self.checkReviews = eval(os.environ.get('checkReviews') or 'True')

        self.swLevel = os.environ.get('swLevel') or 'debug'

        self.loadReferees()

        self.concurrentPages = int(os.environ.get('concurrentPages') or '4')
        activeReferees = len([referee for referee in self.refereeDetails if referee["status"] == "active"])
        if activeReferees < self.concurrentPages:
            self.concurrentPages = activeReferees

        self.logger.info(f'Referees#: {len(self.refereeDetails)} Active#: {activeReferees}')

        self.twilioClient = twilioClient.TwilioClient(self, '+14155238886')
        self.twilioSend = eval(os.environ.get('twilioSend') or 'False')

        # Initialize Firebase Admin SDK
        jsonKeyFile = "path/to/your/serviceAccountKey.json"
        if os.path.exists(jsonKeyFile):
            fbCred = credentials.Certificate(jsonKeyFile)
            firebase_admin.initialize_app(fbCred)

        self.mqttPublish = eval(os.environ.get('mqttPublish') or 'True')
        self.mqttClient = mqttClient.MqttClient(parent=self)

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

    def loadReferees(self):
        self.refereeDetails = []
        try:
            readText = None
            referee_file_path = os.getenv("MY_CONFIG_FILE", f"/run/config/")
            referee_file_path = f'{referee_file_path}refereesDetails'
            with open(referee_file_path, 'r') as refereeDetails_file:
                readText = refereeDetails_file.read().strip()
            self.refereeDetails = json.loads(readText)

        except Exception as ex:
            self.logger.error(f'loadReferees error: {ex}')

        refereeSecretsKey = helpers.get_secret(self, 'refPortal_referees')#None#refPortalSecret and refPortalSecret.get("refPortal_referees", None)
        #refereeSecretsKey = None
        if refereeSecretsKey:
            self.refereeSecrets = json.loads(refereeSecretsKey)
        else:
            self.refereeSecrets = {
                "refId43679" : "S073XdLR"
            }

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

    def getTagText(self, objType, tag, cell, cellText):
        #self.logger.warning(f'tag={tag} {f'{tag}TagDic' in self.dataDic[objType]}')
        if tag and f'{tag}TagDic' in self.dataDic[objType]:
            for filter, useText in self.dataDic[objType][f'{tag}TagDic']:
                #self.logger.warning(self.dataDic[objType][f'{tag}TagDic'])
                if filter == None or filter in str(cell):
                    if cellText:
                        cellText = f'{cellText} ({useText})'
                    else:
                        cellText = useText
                    break
        
        return cellText

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
            if len(rows)<=1:
                result.append(f"אין שיבוצים")
            else:
                for row in rows[1:]:  # Skip the header row
                    cells = row.find_all('td')
                    if len(cells) == len(headers):  # Regular rows
                        for header, cell in zip(headers, cells):
                            cellText = self.getTagText(games, header, cell, cell.get_text(strip=True))
                            if header or cellText:
                                result.append(f"{header}: {cellText}")
                    elif len(cells) == 1:  # Row with colspan
                        html1 = self.transformHtmlTable(str(cells[0]))
                        #self.logger.warning(str(html1))
                        nestedResult = await self.convertGamesTableToText(html1)
                        result.append('')
                        result.append(nestedResult)
                        #self.logger.warning(h.handle(cells[0].decode_contents()))
                        #cellText = self.getTagText(games, header, cells[0], h.handle(cells[0].decode_contents()))
                        #result.append(cellText)
    
        except Exception as e:
            self.logger.error(f'convertGamesTableToText {e}')

        finally:
            return "\n".join(result)

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

        return "\n".join(result)

    async def parseText(self, objType, text):
        try:
            data = self.dataDic[objType]
            listObjects = []
            obj = None
            objText = ''

            if text:
                for line in text.split('\n'):
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
                                        obj["objText"] = objText
                                        listObjects.append(obj)
                                        objText = ''
                                    obj = {}
                                obj[tag] = tagValue
                            elif "refereeSubTags" in data and tag in data["refereeSubTags"]:
                                obj[refereeTag][tag] = tagValue

                            if "excludeCompareTags" not in self.dataDic[objType] or tag not in self.dataDic[objType]["excludeCompareTags"]:
                                objText += f'{line}\n'

                        elif "refereesTags" in data and line and line in data["refereesTags"]:
                            refereeTag = line
                            obj[refereeTag] = {}
                            objText += f'{line}\n'
                        
                if obj:
                    obj["objText"] = objText
                    listObjects.append(obj)

            for obj in listObjects:
                pk = ''
                for tag in data["pkTags"]:
                    pk += obj[tag]
                obj[self.dataDic["pk"]] = pk

            self.logger.debug(f'n={len(listObjects)} {listObjects}')

            return listObjects

        except Exception as e:
            self.logger.error(f'parseText: {e}')
            return None

    async def compareList(self, objType, referee):
        try:
            prevList = referee[objType][f'prevList']
            currentList = referee[objType][f'currentList']

            #Added
            prevListIds = {d[self.dataDic["pk"]] for d in prevList}
            referee[objType]["added"] = [d for d in currentList if d[self.dataDic["pk"]] not in prevListIds]
            referee[objType]["addedText"] = ''
            for item in referee[objType]["added"]:
                referee[objType]["addedText"] += f'{item["objText"]}\n'
                item["1stReminder"] = False
                item["2ndReminder"] = False

            #Removed
            if "removeFilter" in self.dataDic[objType]:
                filteredprevList = []
                for prevListItem in prevList:          
                    gameDate = datetime.strptime(prevListItem["תאריך"], "%d/%m/%y %H:%M")
                    if gameDate >= datetime.now():
                        filteredprevList.append(prevListItem)
            else:
                filteredprevList = prevList

            currentListIds = {d[self.dataDic["pk"]] for d in currentList}
            referee[objType]["removed"] = [d for d in filteredprevList if d[self.dataDic["pk"]] not in currentListIds]
            referee[objType]["removedText"] = ''
            for item in referee[objType]["removed"]:
                referee[objType]["removedText"] += f'{item["objText"]}\n'

            #Changed
            changedList = []
            for prevListItem in prevList:
                for currentListItem in currentList:
                    if prevListItem[self.dataDic["pk"]] == currentListItem[self.dataDic["pk"]] and prevListItem[self.dataDic["objText"]] != currentListItem[self.dataDic["objText"]]:
                        if "1stReminder" in prevListItem:
                            currentListItem["1stReminder"] = prevListItem["1stReminder"]
                        if "2ndReminder" in prevListItem:
                            currentListItem["2ndReminder"] = prevListItem["2ndReminder"]
                        changedList.append(currentListItem)

            referee[objType]["changed"] = changedList
            referee[objType]["changedText"] = ''
            for item in referee[objType]["changed"]:
                referee[objType]["changedText"] += f'{item["objText"]}\n'

            #NonChanged
            nonChangedList = []
            for prevListItem in prevList:
                for currentListItem in currentList:
                    if prevListItem[self.dataDic["pk"]] == currentListItem[self.dataDic["pk"]] and prevListItem[self.dataDic["objText"]] == currentListItem[self.dataDic["objText"]]:
                        if "1stReminder" in prevListItem:
                            currentListItem["1stReminder"] = prevListItem["1stReminder"]
                        if "2ndReminder" in prevListItem:
                            currentListItem["2ndReminder"] = prevListItem["2ndReminder"]
                        nonChangedList.append(currentListItem)

        except Exception as e:
            self.logger.error(f'compareList: {e}')
    
    async def gamesActions(self, objType, referee):
        try:
            self.logger.debug(self.colorText(referee, f'reminders'))
            if "reminders" in referee and referee["reminders"] == "True":
                games = referee[objType][f'currentList']
                
                for game in games:
                    gameDate = datetime.strptime(game["תאריך"], "%d/%m/%y %H:%M")
                    self.logger.debug(self.colorText(referee, f'reminders1 {gameDate}'))

                    if "1stReminder" not in game or game["1stReminder"] == False:
                        game["1stReminder"] = await self.reminder(referee, gameDate, 24, 5, 
                            f'תזכורת ראשונה למשחק {game["מסגרת משחקים"]}:',
                            f"מחר יש לך משחק {game["משחק"]} נא לתאם עם הצוות")
                    
                    if "2ndReminder" not in game or game["2ndReminder"] == False:
                        game["2ndReminder"] = await self.reminder(referee, gameDate, 3, 5, 
                            f'תזכורת אחרונה למשחק {game["מסגרת משחקים"]}:',
                            f'בעוד שלוש שעות מתחיל המשחק {game["משחק"]} נא להערך בהתאם')
                
                referee[objType][f'currentList'] = games

        except Exception as e:
            self.logger.error(f'actions: {len(games)} {e}')

    async def sendGeneralReminders(self, referee):
        now = datetime.now()
        
        next_10am = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= next_10am:
            next_10am += timedelta(days=1)

        await self.reminder(referee, next_10am, 0, 5, 
                            f'תזכורת חידוש רישום',
                            f'https://api.whatsapp.com/send/?phone=%2B14155238886&text=join+of-wheel&type=phone_number&app_absent=0')

        next_10pm = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= next_10pm:
            next_10pm += timedelta(days=1)

        await self.reminder(referee, next_10pm, 0, 2, 
                            f'תזכורת חידוש רישום',
                            f'https://api.whatsapp.com/send/?phone=%2B14155238886&text=join+of-wheel&type=phone_number&app_absent=0')

    async def reminder(self, referee, dueDate, hoursInAdvance, reminderOffsetInMins, title, message):
        reminderInAdvance = hoursInAdvance*60*60
        offset = reminderOffsetInMins*60
    
        if dueDate - timedelta(seconds=reminderInAdvance + offset) < datetime.now() < dueDate - timedelta(seconds=reminderInAdvance):
            await self.send_notification(title, message, referee["id"], referee["mobile"], referee["name"])
            self.logger.debug(self.colorText(referee, f'reminders {dueDate}'))

            return True
        else:
            return False

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

    async def send_notification(self, title, message, toId, toMobile, toName, toDeviceToken=None, sendAt=None):
        #audio.play('')
        #templateSid = 'HX6c220c925c90ee34328a453facd64083'
        #templateSid2 = 'HX229f5a04fd0510ce1b071852155d3e75'
        #title = '12/1'
        #message = '3pm'
        
        #message = 'שובצת ביום רביעי למשחק רבע גמר גביע האלופות בשעה 22:00 למשחק ברצלונה נגד מנצ׳סטר סיטי'
        #message = 'סוג דוח    תאריך   מסגרת משחקים    קבוצה ביתית: קבוצה אורחת        מח.     מגרש    ניווט   סטטוס   ?'
        #fromMobile = fromMobile or '+14155238886'
        #toMobile = toMobile or '+972547799979'
        #self.logger.info(message)
        #message1 = message#.replace('״', "")
        #hti = Html2Image()
        #imageFile = f"output_image_{uuid.uuid4()}.png"
        #hti.screenshot(html_str=message, save_as=imageFile)

        message1 = message
        message1 = message1.replace('"','\"')
        #message1 = message1[:10]
        #content_variables = '{"1":"'+message1+'"}'
        #self.logger.info(f'SENT: {content_variables}')

        if self.twilioSend:
            sentWhatsappMessage = await self.twilioClient.send(toMobile=toMobile, message=f'**{title}**\n{message1}', sendAt=sendAt)

        if self.mqttPublish:
            await self.mqttClient.publish(title=title, message=message1, id=toId)

        if toDeviceToken:
            await self.send_push_notification(deviceToken=toDeviceToken, title=title, body=message1)

    async def notifyUpdate(self, objType, referee):
        try:
            message = ''
            if f"forceSend" in referee[objType] and referee[objType][f"forceSend"] == True:
                message = referee[objType][f'currentList']
            else:
                if len(referee[objType]["added"]) > 0:
                    message += f'*חדש*\n{referee[objType]["addedText"]}\n'
                    self.logger.debug(self.colorText(referee, f'{objType} added list#{len(referee[objType]["added"])}={referee[objType]["added"]}')) 

                if len(referee[objType]["removed"]) > 0:
                    message += f'*נמחק*\n~{referee[objType]["removedText"]}~\n'
                    self.logger.debug(self.colorText(referee, f'{objType} removed list#{len(referee[objType]["removed"])}={referee[objType]["removed"]}'))

                if len(referee[objType]["changed"]) > 0:
                    message += f'*עדכון*\n{referee[objType]["changedText"]}\n'
                    self.logger.debug(self.colorText(referee, f'{objType} changed list#{len(referee[objType]["changed"])}={referee[objType]["changed"]}'))

            if len(referee[objType]["added"]) > 0:
                message += f'{self.loginUrl}'

            self.logger.info(self.colorText(referee, f'notify: {objType}: {message}'))
        
            title = self.dataDic[objType]["notifyTitle"]
            await self.send_notification(title, message, referee["id"], referee["mobile"], referee["name"])
        except Exception as e:
            self.logger.error(f'notifyUpdate: {e}')

    def getRefereeFilePath(self, objType, referee):
        try:
            referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
            referee_file_path = f'{referee_file_path}refId{referee["refId"]}_{objType}_{self.fileVersion}'

            return referee_file_path
        except Exception as e:
            pass

    async def readRefereeFile(self, objType, referee):
        readFileText = None
        file_datetime = None
        
        try:
            referee_file_path = self.getRefereeFilePath(objType, referee)
            self.logger.debug(f'file: {referee_file_path}')
            if objType not in referee:
                referee[objType] = {}
            if os.path.exists(referee_file_path):
                file_datetime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                with open(referee_file_path, 'r') as referee_file:
                    readFileText = referee_file.read().strip()
                self.logger.debug(f'readFileText: {readFileText}')                
                referee[objType]['currentList'] = json.loads(readFileText)
            else:
                file_datetime = datetime.now()
                referee[objType]['currentList'] = []
            if 'prevList' not in referee[objType]:
                referee[objType]['prevList'] = []
            referee[objType]['fileDateTime'] = file_datetime.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            self.logger.error(f'readRefereeFile {e}')

    async def writeRefereeFile(self, objType, referee):
        try:
            prevListText = json.dumps(referee[objType]['prevList'], ensure_ascii=False)
            currentListText = json.dumps(referee[objType]['currentList'], ensure_ascii=False)
            referee_file_path = self.getRefereeFilePath(objType, referee)
            dir = os.path.dirname(referee_file_path)
            self.logger.debug(f'file: {dir} {referee_file_path}')
            if dir and not os.path.exists(dir):
                self.logger.debug(f'create dir: {dir}')
                os.makedirs(dir)
            if prevListText != currentListText or not os.path.exists(referee_file_path):
                self.logger.debug(f'prev:{prevListText}')
                self.logger.debug(f'current:{currentListText}')
                if os.path.exists(referee_file_path):
                    fileDateTime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                    shutil.copy(referee_file_path, f'{referee_file_path}_{fileDateTime}')
                refereeDumps = json.dumps(referee[objType]['currentList'], ensure_ascii=False)
                with open(referee_file_path, 'w') as referee_file:
                    referee_file.write(refereeDumps.strip())
        except Exception as e:
            self.logger.error(f'writeFileText: {e}')

    async def checkRefereeTask(self, manager, referee):
        semaphore, page = await manager.acquire_page()
        self.logger.debug(self.colorText(referee, f'seq={referee["seq"]}'))
        referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
        try:
            await self.sendGeneralReminders(referee)

            await self.login(referee, page)
            self.logger.debug(self.colorText(referee, f'after login'))

            if self.checkGames:
                await self.checkRefereeData("games", referee, page)
 
            if self.checkReviews:
                await self.checkRefereeData("reviews", referee, page)

        except Exception as ex:
            self.logger.error(f'CheckRefereeTask error: {ex}')

        finally:
            loggedoutSuccessfully = await self.logout(referee, page)
            self.logger.debug(self.colorText(referee, f'loggedoutSuccessfully={loggedoutSuccessfully}'))
            if loggedoutSuccessfully == True:
                manager.release_page(semaphore, page)
            else:
                manager.renew_page(semaphore, page)
            #await manager.context.tracing.stop(path=f"{referee_file_path}traceFinally{datetime.now().strftime("%Y%m%d%H%M%S")}}.zip")

    async def checkRefereeData(self, objType, referee, page):
        try:
            swName = f'checkRefereeData={referee["name"]}{objType}'
            helpers.stopwatch_start(self, swName)

            helpers.stopwatch_start(self, f'{swName}ReadFile')
            await self.readRefereeFile(objType, referee)
            helpers.stopwatch_stop(self, f'{swName}ReadFile', level=self.swLevel)

            found = False
            hText = None

            for i in range(2):
                helpers.stopwatch_start(self, f'{swName}Url')
                await page.goto(self.dataDic[objType]["url"])
                await page.wait_for_load_state(state='load', timeout=5000)
                helpers.stopwatch_stop(self, f'{swName}Url', level=self.swLevel)

                cnt = 0
                for j in range(5):
                    t = i * 5 + j + 1
                    #self.logger.warning(f'{i} {j} {t}')
                    helpers.stopwatch_start(self, f'{swName}Read')
                    await asyncio.sleep(150 * (j + 1) / 1000)
                    self.logger.debug(f'url={page.url}')
                    result = await self.dataDic[objType]["read"](page)
                    title = await page.title()
                    self.logger.debug(self.colorText(referee, f'title: {title}'))
                    table_outer_html = None
                    if result:
                        table_outer_html = await result.evaluate("element => element.outerHTML")
                    helpers.stopwatch_stop(self, f'{swName}Read', level=self.swLevel)
                    #self.logger.warning(f'table_outer_html: {objType} {table_outer_html}')
                    helpers.stopwatch_start(self, f'{swName}Convert')
                    hText = await self.dataDic[objType]["convert"](table_outer_html)
                    hText = hText.strip()
                    #self.logger.warning(hText)
                    helpers.stopwatch_stop(self, f'{swName}Convert', level=self.swLevel)

                    if hText:
                        parsedList = None
                        if "parse" in self.dataDic[objType] and self.dataDic[objType]["parse"]:
                            helpers.stopwatch_start(self, f'{swName}parse')
                            parsedList = await self.dataDic[objType]["parse"](objType, hText)
                            helpers.stopwatch_stop(self, f'{swName}parse', level=self.swLevel)

                            if parsedList and len(parsedList) > 0:
                                found = True
                                cnt = len(parsedList)

                        elif "parse" not in self.dataDic[objType] and len(hText) > len(referee[objType][f"prevText"]):
                            found = True

                        self.logger.debug(self.colorText(referee, f'parse objType={objType} t={t} found={found} parsedList={cnt}'))
            
                        referee[objType][f'prevList'] = referee[objType][f'currentList']
                        referee[objType][f'currentList'] = parsedList
                        self.logger.debug(self.colorText(referee, f'list {referee}'))

                        if found == True:
                            break

                if found == True or f'prevList' in referee[objType] and len(referee[objType]['prevList']) == 0:
                    break

            if hText:
                if "compare" in self.dataDic[objType] and self.dataDic[objType]["compare"]:
                    await self.dataDic[objType]["compare"](objType, referee)
                    
                    await self.writeRefereeFile(objType, referee)
                    
                    if len(referee[objType]["added"]) > 0 or len(referee[objType]["removed"]) > 0 or len(referee[objType]["changed"]) > 0 or f"forceSend" in referee[objType] and referee[objType][f"forceSend"] == True:
                        self.logger.info(self.colorText(referee, f'{objType} A:{len(referee[objType]["added"])} R:{len(referee[objType]["removed"])} C:{len(referee[objType]["changed"])} #{cnt}/{t}'))

                        await self.dataDic[objType]["notify"](objType, referee)
                    else:
                        fileDateText = referee[objType][f"fileDateTime"]
                        self.logger.info(self.colorText(referee, f'No {objType} update since {fileDateText} #{cnt}/{t}'))
            
                if f'currentList' in referee[objType] and referee[objType][f'currentList'] \
                        and "actions" in self.dataDic[objType] and self.dataDic[objType]["actions"]:
                    await self.dataDic[objType]["actions"](objType, referee)
                
            helpers.stopwatch_stop(self, f'{swName}', level=self.swLevel)
        except Exception as ex:
            self.logger.error(f'CheckRefereeData error: {ex}')

    def colorText(self, referee, text):
        color = Fore.WHITE
        try:
            if 'color' in referee and referee['color']:
                color = eval(f'Fore.{referee["color"]}')
        except Exception as ex:
            pass
        return f'{color}{referee["name"]}:{text}{Style.RESET_ALL}'

    async def login(self, referee, page):
        try:
            t=0
            while page.url != self.gamesUrl and t < 10:
                t+=1
                self.logger.debug(self.colorText(referee, f'login#{t}'))
                await page.goto(self.loginUrl)
                #await page.wait_for_load_state(state='load', timeout=2000)
                await asyncio.sleep(1000*t / 1000)

                input_elements = await page.query_selector_all('input')
                if len(input_elements) == 3:
                    usernameField = input_elements[0]
                    await usernameField.fill(referee["refId"])

                    passwordField = input_elements[1]
                    await passwordField.fill(self.refereeSecrets[f'refId{referee["refId"]}'])

                    idField = input_elements[2]
                    await idField.fill(referee["id"])

                    # Find the submit button and click it
                    button_elements = await page.query_selector_all('button')
                    mainButton = button_elements[0]
                    await mainButton.click()  # Replace selector as needed
                    await asyncio.sleep(1000 / 1000)

            await asyncio.sleep(1000 / 1000)

            if page.url != self.gamesUrl:
                self.logger.error(self.colorText(referee, f'Login failed#{t}'))
            else:
                self.logger.debug(self.colorText(referee, f'Login successfull#{t}'))

        except Exception as ex:
            self.logger.error(f'Login error: {ex}')

    async def logout(self, referee, page):
        try:
            t=0
            while page.url != self.loginUrl and t < 10:
                t+=1
                self.logger.debug(self.colorText(referee, f'logout#{t}'))
                button_elements = await page.query_selector_all("button")
                logoutButtons = [button for button in button_elements if (await button.inner_text()).strip() == "יציאה"]

                self.logger.debug(f'logoutButtons={len(logoutButtons)}')
                if len(logoutButtons) == 1:
                    logoutButton = button_elements[0]
                    await logoutButton.click()
                    #await page.wait_for_load_state(state='load', timeout=5000)
                await asyncio.sleep(1000*t / 1000)

            if page.url != self.loginUrl:
                self.logger.error(self.colorText(referee, f'Logout failed#{t}'))
            else:
                self.logger.debug(self.colorText(referee, f'Logout successfull#{t}'))

        except Exception as ex:
            self.logger.error(f'logout error: {ex}')
            return False
    
        return True
    
    async def approveGame(self, referee, page, i):
        self.logger.debug(self.colorText(referee, f'approve'))
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

        await self.mqttClient.publish("RefPortal Start", self.openText)

        try:
            async with async_playwright() as p:                
                browser = await p.firefox.launch(headless=True, args=['--disable-dev-shm-usage','--disable-extensions','--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-software-rasterizer','--verbose'])
                context = await browser.new_context()
                #p.debug = 'pw:browser,pw:page'
                #await context.tracing.start(screenshots=True, snapshots=True)
                manager = pageManager.PageManager(context, self.concurrentPages)
                await manager.initialize_pages()

                i=0
                for referee in self.refereeDetails:
                    referee["seq"] = i
                    i+=1

                while True:
                    try:
                        refereesTasks = [self.checkRefereeTask(manager, referee) for referee in self.refereeDetails if referee["status"] == "active"]
                        await asyncio.gather(*refereesTasks)

                    except Exception as ex:
                        self.logger.error(f'Start error: {ex}')
                    finally:
                        await asyncio.sleep(self.pollingInterval / 1000)

        except Exception as ex:
            self.logger.error(f'Error: {ex}')
        
        finally:
            self.logger.debug(f'close')
            if browser:# and context:
                await browser.close()
            # Disconnect the client
            self.mqttClient.disconnect()

if __name__ == "__main__":
    app = None
    try:
        print("Hello RefPortalllll")
        app = RefPortalApp()
        app.logger.info(f'Main run')
        asyncio.run(app.start())
        pass
    except Exception as ex:
        print(f'Main Error: {ex}')
        pass