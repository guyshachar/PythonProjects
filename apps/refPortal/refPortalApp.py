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
                "compare": self.listCompare,
                "actions": self.gamesActions,
                "notify": self.notifyUpdate,
                "notifyTitle" : "שיבוצים:",
                "tags" : [ "תאריך", "יום", "מסגרת משחקים", "משחק", "סבב", "מחזור", "מגרש", "סטטוס" ],
                "סטטוסTagDic": [("15.svg", "מאושר"), ("16.svg", "מחכה לאישור"), ("17.svg", "לא מאושר")],
                "initTag" : "תאריך",
                "refereesTags" : [ "שופט ראשי", "ע. שופט 1", "ע. שופט 2", "שופט רביעי", "שופט שני", "שופט ראשון", "שופט מזכירות" ],
                "refereeSubTags" : [ "* שם", "* דרג", "* טלפון", "* כתובת" ],
                "pkTags": ["מסגרת משחקים", "משחק"],
                "removeFilter": "תאריך"
           },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "read": self.readPortalReviews,
                "convert": self.convertReviewsTableToText,
                "parse": self.parseText,
                "compare": self.listCompare,
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
        if len(self.refereeDetails) < self.concurrentPages:
            self.concurrentPages = len(self.refereeDetails)

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
            table_elements = await page.query_selector_all('table')
            if len(table_elements) > 0:
                result = table_elements[0]

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

            for referee in self.refereeDetails:
                referee["logger"] = logging.getLogger(f'{__name__}_{referee["name"]}')

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

        self.logger.info(f'Referees#: {len(self.refereeDetails)}')

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
    
    async def convertGamesTableToText(self, html):
        games = "games"
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
        result = []
        if len(rows)==1:
            result.append(f"אין שיבוצים")
        else:
            for row in rows[1:]:  # Skip the header row
                cells = row.find_all('td')
                if len(cells) == len(headers):  # Regular rows
                    for header, cell in zip(headers, cells):
                        cellText = ''
                        if header and f'{header}TagDic' in self.dataDic[games]:
                            for filter, useText in self.dataDic[games][f'{header}TagDic']:
                                if filter in str(cell):
                                    cellText = useText
                                    break
                        else:
                            cellText = cell.get_text(strip=True)
                        if header or cellText:
                            result.append(f"{header}: {cellText}")
                elif len(cells) == 1:  # Row with colspan
                    result.append(h.handle(cells[0].decode_contents()))

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

    async def parseText(self, type, text):
        try:
            data = self.dataDic[type]
            listObjects = []
            obj = None
            objText = ''
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

                        if "excludeCompareTags" not in self.dataDic[type] or tag not in self.dataDic[type]["excludeCompareTags"]:
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
            self.logger.error(f'parse: {e}')
            return None

    async def listCompare(self, type, referee):
        try:
            last = referee[f'last_{type}List']
            current = referee[f'{type}List']

            #Added
            lastIds = {d[self.dataDic["pk"]] for d in last}
            referee["added"] = [d for d in current if d[self.dataDic["pk"]] not in lastIds]
            referee["addedText"] = ''
            for item in referee["added"]:
                referee["addedText"] += f'{item["objText"]}\n'

            #Removed
            if "removeFilter" in self.dataDic[type]:
                filteredLast = []
                for lastItem in last:          
                    gameDate = datetime.strptime(lastItem["תאריך"], "%d/%m/%y %H:%M")
                    if gameDate >= datetime.now():
                        filteredLast.append(lastItem)
            else:
                filteredLast = last

            currentIds = {d[self.dataDic["pk"]] for d in current}
            referee["removed"] = [d for d in filteredLast if d[self.dataDic["pk"]] not in currentIds]
            referee["removedText"] = ''
            for item in referee["removed"]:
                referee["removedText"] += f'{item["objText"]}\n'

            #Changed
            changedList = []
            for lastItem in last:
                for currentItem in current:
                    if lastItem[self.dataDic["pk"]] == currentItem[self.dataDic["pk"]] and lastItem[self.dataDic["objText"]] != currentItem[self.dataDic["objText"]]:
                        changedList.append(currentItem)

            referee["changed"]=changedList
            referee["changedText"] = ''
            for item in referee["changed"]:
                referee["changedText"] += f'{item["objText"]}\n'
        except Exception as e:
            self.logger.error(f'listCompare: {e}')
    
    async def gamesActions(self, type, referee, games):
        try:
            self.logger.debug(self.colorText(referee, f'reminders'))
            if games:
                for game in games:
                    gameDate = datetime.strptime(game["תאריך"], "%d/%m/%y %H:%M")
                    if "reminders" in referee and referee["reminders"] == "True":
                        self.logger.debug(self.colorText(referee, f'reminders1 {gameDate}'))

                        await self.reminder(referee, gameDate, 24, 1.5, 
                            f'תזכורת ראשונה למשחק {game["מסגרת משחקים"]}:',
                            f"מחר יש לך משחק {game["משחק"]} נא לתאם עם הצוות")

                        await self.reminder(referee, gameDate, 3, 1.5, 
                            f'תזכורת אחרונה למשחק {game["מסגרת משחקים"]}:',
                            f'בעוד שלוש שעות מתחיל המשחק {game["משחק"]} נא להערך בהתאם')
        except Exception as e:
            self.logger.error(f'actions: {len(games)} {e}')

    async def sendGeneralReminders(self, referee):
        now = datetime.now()
        next_10am = now.replace(hour=10, minute=0, second=0, microsecond=0)

        # If it's already past 9:00 AM today, schedule for the next day
        if now >= next_10am:
            next_10am += timedelta(days=1)

        await self.reminder(referee, next_10am, 0, 1.5, 
                            f'תזכורת חידוש רישום',
                            f'https://api.whatsapp.com/send/?phone=%2B14155238886&text=join+of-wheel&type=phone_number&app_absent=0')

    async def reminder(self, referee, dueDate, hoursInAdvance, reminderOffsetInMins, title, message):
        reminderInAdvance = hoursInAdvance*60*60
        offset = reminderOffsetInMins*60
    
        if dueDate - timedelta(seconds=reminderInAdvance + offset) < datetime.now() < dueDate - timedelta(seconds=reminderInAdvance):
            await self.send_notification(title, message, referee["id"], referee["mobile"], referee["name"])
            self.logger.debug(self.colorText(referee, f'reminders {dueDate}'))

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

    async def notifyUpdate(self, type, referee):
        try:
            message =''
            if len(referee["added"]) > 0:
                message += f'*חדש*\n{referee["addedText"]}\n'
                self.logger.debug(self.colorText(referee, f'{type} added list#{len(referee["added"])}={referee["added"]}')) 

            if len(referee["removed"]) > 0:
                message += f'*נמחק*\n{referee["removedText"]}\n'
                self.logger.debug(self.colorText(referee, f'{type} removed list#{len(referee["removed"])}={referee["removed"]}'))

            if len(referee["changed"]) > 0:
                message += f'*עדכון*\n{referee["changedText"]}\n'
                self.logger.debug(self.colorText(referee, f'{type} changed list#{len(referee["changed"])}={referee["changed"]}'))

            if len(referee["added"]) > 0:
                message += f'{self.loginUrl}'

            self.logger.info(self.colorText(referee, f'notify: {type}: {message}'))
        
            title = self.dataDic[type]["notifyTitle"]
            await self.send_notification(title, message, referee["id"], referee["mobile"], referee["name"])
        except Exception as e:
            self.logger.error(f'notifyUpdate: {e}')

    async def readRefereeFile(self, type, referee):
        readFileText = None
        try:
            referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
            referee_file_path = f'{referee_file_path}refId{referee["refId"]}_{type}'
            with open(referee_file_path, 'r') as referee_file:
                readFileText = referee_file.read().strip()
        except Exception as e:
            pass

        self.logger.debug(f'readFileText: {readFileText}')
        return readFileText

    async def writeRefereeFile(self, type, refId, writeFileText):
        try:
            referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
            self.logger.debug(f'check dir: {referee_file_path}')
            if referee_file_path and not os.path.exists(referee_file_path):
                self.logger.debug(f'create dir: {referee_file_path}')
                os.makedirs(referee_file_path)
            referee_file_path = f'{referee_file_path}refId{refId}_{type}'
            if os.path.exists(referee_file_path):
                fileDateTime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                shutil.copy(referee_file_path, f'{referee_file_path}_{fileDateTime}')
            with open(referee_file_path, 'w') as referee_file:
                referee_file.write(writeFileText.strip())
        except Exception as e:
            self.logger.error(f'writeFileText: {e}')

    async def checkRefereeTask(self, manager, referee):
        semaphore, page = await manager.acquire_page()
        self.logger.debug(self.colorText(referee, f'seq={referee["seq"]}'))
        #page = manager.get_page(referee["seq"])
        referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
        try:
            await self.sendGeneralReminders(referee)

            await self.login(referee, page)
            self.logger.debug(self.colorText(referee, f'after login {type}'))

            if self.checkGames:
                await self.checkRefereeData("games", referee, page)
 
            if self.checkReviews:
                await self.checkRefereeData("reviews", referee, page)

        except Exception as ex:
            self.logger.error(f'CheckRefereeTask error: {ex}')
            fileDateTime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
            #await manager.context.tracing.stop(path=f"{referee_file_path}traceExcept{datetime.now().strftime("%Y%m%d%H%M%S")}}.zip")

        finally:
            loggedoutSuccessfully = await self.logout(referee, page)
            self.logger.debug(self.colorText(referee, f'loggedoutSuccessfully={loggedoutSuccessfully}'))
            if loggedoutSuccessfully == True:
                manager.release_page(semaphore, page)
            else:
                manager.renew_page(semaphore, page)
            #await manager.context.tracing.stop(path=f"{referee_file_path}traceFinally{datetime.now().strftime("%Y%m%d%H%M%S")}}.zip")

    async def checkRefereeData(self, type, referee, page):
        swName = f'checkRefereeData={referee["name"]}{type}'
        helpers.stopwatch_start(self, swName)

        helpers.stopwatch_start(self, f'{swName}ReadFile')
        readFile = await self.readRefereeFile(type, referee)
        referee[f'last_{type}Text'] = readFile
        if "parse" in self.dataDic[type] and self.dataDic[type]["parse"]:
            parsedList = await self.dataDic[type]["parse"](type, readFile)
            referee[f'last_{type}List'] = parsedList
        helpers.stopwatch_stop(self, f'{swName}ReadFile', level=self.swLevel)

        found = False
        hText = None

        for i in range(2):
            helpers.stopwatch_start(self, f'{swName}Url')
            await page.goto(self.dataDic[type]["url"])
            await page.wait_for_load_state(state='load', timeout=5000)
            helpers.stopwatch_stop(self, f'{swName}Url', level=self.swLevel)

            cnt = 0
            for j in range(5):
                t = i * 5 + j + 1
                #self.logger.warning(f'{i} {j} {t}')
                helpers.stopwatch_start(self, f'{swName}Read')
                await asyncio.sleep(150 * (j + 1) / 1000)
                self.logger.debug(f'url={page.url}')
                result = await self.dataDic[type]["read"](page)
                title = await page.title()
                self.logger.debug(self.colorText(referee, f'title: {title}'))
                table_outer_html = await result.evaluate("element => element.outerHTML")
                helpers.stopwatch_stop(self, f'{swName}Read', level=self.swLevel)
                #self.logger.info(f'table_outer_html: {table_outer_html}')
                helpers.stopwatch_start(self, f'{swName}Convert')
                hText = await self.dataDic[type]["convert"](table_outer_html)
                hText = hText.strip()
                helpers.stopwatch_stop(self, f'{swName}Convert', level=self.swLevel)

                parsedList = None
                if "parse" in self.dataDic[type] and self.dataDic[type]["parse"]:
                    helpers.stopwatch_start(self, f'{swName}ParseActions')
                    parsedList = await self.dataDic[type]["parse"](type, hText)
                    if parsedList and "actions" in self.dataDic[type] and self.dataDic[type]["actions"]:
                        await self.dataDic[type]["actions"](type, referee, parsedList)
                    helpers.stopwatch_stop(self, f'{swName}ParseActions', level=self.swLevel)

                    if parsedList and len(parsedList) > 0:
                        found = True
                        cnt = len(parsedList)

                elif "parse" not in self.dataDic[type] and len(hText) > len(referee[f"last_{type}Text"]):
                    found = True

                self.logger.debug(self.colorText(referee, f'parseactions type={type} t={t} found={found} parsedList={cnt}'))
    
                referee[f'{type}List'] = parsedList
                self.logger.debug(self.colorText(referee, f'list {referee}'))

                if found == True:
                    break

            if found == True or len(referee[f'last_{type}List']) == 0:
                break

        if hText:
            if "compare" in self.dataDic[type] and self.dataDic[type]["compare"]:
                await self.dataDic[type]["compare"](type, referee)
                
                # Update file if text changed
                if hText != referee[f"last_{type}Text"]:
                    await self.writeRefereeFile(type, referee["refId"], hText)
                
                if len(referee["added"]) > 0 or len(referee["removed"]) or len(referee["changed"]):
                    self.logger.info(self.colorText(referee, f'{type} A:{len(referee["added"])} R:{len(referee["removed"])} C:{len(referee["changed"])} #{cnt}/{t}'))

                    referee[f"last_{type}Text"] = hText
                    referee[f"last_{type}Text_time"] = f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

                    await self.dataDic[type]["notify"](type, referee)
                else:
                    self.logger.info(self.colorText(referee, f'No {type} update since {referee[f"last_{type}Text_time"]} #{cnt}/{t}'))
        
        helpers.stopwatch_stop(self, f'{swName}', level=self.swLevel)

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
                    referee["last_gamesText_time"] = None
                    referee["last_reviewsText_time"] = None
                    referee["seq"] = i
                    i+=1
                while True:
                    try:
                        refereesTasks = [self.checkRefereeTask(manager, referee) for referee in self.refereeDetails]
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