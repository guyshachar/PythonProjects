#import appdaemon.plugins.hass.hassapi as hass

#from Shared.logger import Logger
import logging
#import time
from datetime import datetime
import json
import os
import shutil
import asyncio
from playwright.async_api import async_playwright
from twilio.rest import Client as TwilioClient
#from html2image import Html2Image
from bs4 import BeautifulSoup
import html2text
import boto3
from botocore.exceptions import ClientError
import firebase_admin
from firebase_admin import credentials, messaging
import paho.mqtt.client as mqtt
import helpers

#class RefPortalApp(hass.Hass):
class RefPortalApp():
    def __init__(self):
        #self.call_service("mqtt/publish", topic='my/mqtt/refPortal/init', payload=f'now={datetime.now().timestamp()}', qos=1)

        #Logger(self)   
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
     
        self.logger.info("Ref Portal")
        
        self.loginUrl = os.environ.get('loginUrl') or 'https://ref.football.org.il/login'
        self.gamesUrl = os.environ.get('gamesUrl') or 'https://ref.football.org.il/referee/home'
        self.reviewsUrl = os.environ.get('reviewsUrl') or 'https://ref.football.org.il/referee/reviews'
        self.dataDic = {
            "games" : {
                "url": "https://ref.football.org.il/referee/home",
                "read": self.readPortalGames,
                "convert": self.convertGamesTableToText,
                "notify": self.notifyGamesUpdate
            },
            "reviews": {
                "url" : "https://ref.football.org.il/referee/reviews",
                "read": self.readPortalReviews,
                "convert": self.convertReviewsTableToText,
                "notify": self.notifyReviewsUpdate
            }
        }
        self.pollingInterval = int(os.environ.get('loadInterval') or '20000')
        self.alwaysClosePage = eval(os.environ.get('alwaysClosePage') or 'True')
        self.checkGames = eval(os.environ.get('checkGames') or 'True')
        self.checkReviews = eval(os.environ.get('checkReviews') or 'True')

        #secretName = os.environ.get('refPortalSM') or "refPortal/referees2"
        #refPortalSecret = self.get_secret(secretName)
        refereesKey = self.get_secret('refPortal_referees')#None#refPortalSecret and refPortalSecret.get("refPortal_referees", None)
        refereesKey = None
        if refereesKey:
            self.referees = json.loads(refereesKey)
        else:
            self.referees = [
            {
                "name": "guy",
                "refId": "43679",
                "refPass": "S073XdLR",
                "id": "025092271",
                "mobile": "+972547799979"
            }
            ]
        self.logger.info(f'Referees#: {len(self.referees)}')
        
        account_sid = self.get_secret('twilio_account_sid')#refPortalSecret and refPortalSecret.get("twilio_account_sid", None)
        auth_token = self.get_secret('twilio_auth_token')#refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
        logging.getLogger("twilio").setLevel(logging.WARNING)
        self.twilioClient = TwilioClient(account_sid, auth_token)
        self.twilioFromMobile = '+14155238886'
        self.twilioSend = eval(os.environ.get('twilioSend') or 'True')

        # Initialize Firebase Admin SDK
        jsonKeyFile = "path/to/your/serviceAccountKey.json"
        if os.path.exists(jsonKeyFile):
            fbCred = credentials.Certificate(jsonKeyFile)
            firebase_admin.initialize_app(fbCred)

        self.mqttPublish = eval(os.environ.get('mqttPublish') or 'True')
        self.mqttClient = None

        self.logger.info(f'url={self.loginUrl} interval={self.pollingInterval} twilio={self.twilioSend} mqtt={self.mqttPublish}')

        pass

    def initialize(self):
        self.start()
        pass

    def get_secret(self, secretName):
        secret_file_path = os.getenv("MY_SECRET_FILE", f"/run/secrets/")
        secret_file_path = secret_file_path + secretName
        try:
            with open(secret_file_path, 'r') as secret_file:
                secret = secret_file.read().strip()
            return secret
        except FileNotFoundError:
            self.logger.error(f"Secret: file not found: {secret_file_path}")
            return None
        except Exception as e:
            self.logger.error(f'secret: {e}')
    
    def get_secret1(self, secretName):
        self.logger.debug(f'secret: {secretName}')
        region_name = "il-central-1"
        secret = None

        # Create a Secrets Manager client
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name
        )

        try:
            self.logger.debug(f'secret: Get Value')
            get_secret_value_response = client.get_secret_value(
                SecretId=secretName
            )
            self.logger.debug(f'secret: Get Value String')
            secretStr = get_secret_value_response['SecretString']
            #self.logger.info(f'secretStr: {secretStr}')
            secret = json.loads(secretStr)
            #self.logger.info(f'secretStr: {secret}')
            return secret
 
        except ClientError as e:
            # For a list of exceptions thrown, see
            # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
            #raise e
            self.logger.error(f'secret clientError: {e}')
            pass
        except Exception as e:
            self.logger.error(f'secret: {e}')
            pass

        return None

    async def readPortalGames(self, page):
        result = None
        try:
            self.logger.debug(f'before readPortalGames')
            table_elements = await page.query_selector_all('table')
            if len(table_elements) > 0:
                result = table_elements[0]

        except Exception as ex:
            self.logger.error(f'readPortal error: {ex}')

        finally:        
            self.logger.debug(f'after readPortalGames')
            return result

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
            result.append(f"אין שיבוצים")
        else:
            for row in rows[1:]:  # Skip the header row
                cells = row.find_all('td')
                if len(cells) == len(headers):  # Regular rows
                    for header, cell in zip(headers, cells):
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

    # Function to send a push notification
    async def send_push_notification(self, deviceToken, title, body):
        # Create a message
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

    async def send_notification(self, title, message, fromMobile, toId, toMobile, toName, toDeviceToken=None):
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

        message1 = f'{title}\n' + message
        message1 = message1.replace('"','\"')
        #message1 = message1[:10]
        #content_variables = '{"1":"'+message1+'"}'
        #self.logger.info(f'SENT: {content_variables}')

        if self.twilioSend:
            """
            sentMessage = self.twilioClient.messages.create(
                from_=f'whatsapp:{fromMobile}',
                content_sid=templateSid2,
                content_variables={"1":"409173"},
                to=f'whatsapp:{toMobile}'
            )
            """
            sizeLimit = 1500
            chunks = helpers.split_text(message1, sizeLimit)
            i=0
            for chunk in chunks:
                if len(chunks) == 1:                
                    message2 = chunk
                else:
                    i+=1
                    message2 = f'#{i} {chunk}'
                sentWhatsappMessage = self.twilioClient.messages.create(
                    from_=f'whatsapp:{fromMobile}',
                    to=f'whatsapp:{toMobile}',
                    body=f'{message2}'
                )

            self.logger.info(f'Whatsapp message.id: {sentWhatsappMessage.sid} {sentWhatsappMessage.status}')
            """
            sentSmsMessage = self.twilioClient.messages.create(
                from_=f'{fromMobile}',
                to=f'{toMobile}',
                body=f'{message1}'
            )

            self.logger.info(f'Sms message.id: {sentSmsMessage.sid} {sentSmsMessage.status}')
            """
        if self.mqttPublish:
            await self.publish_mqtt(title, message1, toId)

        if toDeviceToken:
            await self.send_push_notification(toDeviceToken, title, message1)

    async def publish_mqtt(self, title, message, toId):
        try:
            if not self.mqttClient:
                try:
                    mqttBroker = self.get_secret('mqtt_broker') # Replace with your broker's address
                    mqttPort = 1883                   # Typically 1883 for unencrypted, 8883 for encrypted
                    self.mqttTopic = 'my/mqtt/refPortal'
                    self.mqttClient = mqtt.Client()
                    mqtt_username = self.get_secret('mqtt_username')
                    mqtt_password = self.get_secret('mqtt_password')
                    self.logger.debug(f'mqtt: {mqttBroker} {mqtt_username}/{mqtt_password}')
                    self.mqttClient.username_pw_set(username=mqtt_username, password=mqtt_password)
                    self.mqttClient.connect(mqttBroker, mqttPort)
                finally:
                    pass

            # Publish a message
            message1 = message
            message1 = message1.replace('"',"'")
            message1 = message1.replace('\n','   ')
            response = self.mqttClient.publish(topic=f'{self.mqttTopic}/{toId}', payload=message1)
            self.logger.info(f"Mqtt: Message '{message}' published to topic '{self.mqttTopic}' {response}")

        except Exception as e:
            self.logger.error(f"Mqtt: An error occurred: {e}")

    async def notifyGamesUpdate(self, referee):
        self.logger.info(f'result: {referee["name"]}: {referee["last_gamesText_time"]} {referee["last_gamesText"]}')
        
        try:
            title = f'שיבוצים של {referee["name"]}:'
            await self.send_notification(title, referee["last_gamesText"], self.twilioFromMobile, referee["id"], referee["mobile"], referee["name"])
        finally:
            pass

    async def notifyReviewsUpdate(self, referee):
        self.logger.info(f'result: {referee["name"]}: {referee["last_reviewsText_time"]} {referee["last_reviewsText"]}')
        
        try:
            title = f'ביקורות של {referee["name"]}:'
            await self.send_notification(title, referee["last_reviewsText"], self.twilioFromMobile, referee["id"], referee["mobile"], referee["name"])
        finally:
            pass

    async def readRefereeText(self, type, referee):
        readText = None
        try:
            referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
            referee_file_path = f'{referee_file_path}refId{referee["refId"]}_{type}'
            with open(referee_file_path, 'r') as referee_file:
                readText = referee_file.read().strip()
        except Exception as e:
            pass

        referee[f'last_{type}Text'] = readText
        self.logger.debug(f'Read: {readText}')

    async def writeRefereeText(self, type, referee):
        try:
            referee_file_path = os.getenv("MY_REFEREE_FILE", f"/run/referees/")
            self.logger.debug(f'check dir: {referee_file_path}')
            if referee_file_path and not os.path.exists(referee_file_path):
                self.logger.debug(f'create dir: {referee_file_path}')
                os.makedirs(referee_file_path)
            referee_file_path = f'{referee_file_path}refId{referee["refId"]}_{type}'
            if os.path.exists(referee_file_path):
                fileDateTime = datetime.fromtimestamp(os.path.getmtime(referee_file_path))
                shutil.copy(referee_file_path, f'{referee_file_path}_{fileDateTime}')
            with open(referee_file_path, 'w') as referee_file:
                referee_file.write(referee[f'last_{type}Text'].strip())
        except Exception as e:
            self.logger.error(f'write: {e}')

    async def checkReferee(self, referee):
        try:
            if self.checkGames:
                await self.checkRefereeData("games", referee)
            
            if self.checkReviews:
                await self.checkRefereeData("reviews", referee)

        except Exception as ex:
            if referee["page"]:
                await referee["page"].close()
                referee["page"] = None
            self.logger.error(f'Error3: {ex}')

    async def checkRefereeData(self, type, referee):
        #return
        self.logger.debug(f'{type}')
        page = referee['page']
        await page.goto(self.dataDic[type]["url"])
        await page.wait_for_load_state(state='load', timeout=5000)
        self.logger.debug(f'url={page.url}')

        input_elements = await page.query_selector_all('input')
        if page.url == 'about:blank' or len(input_elements) >= 3:
            await self.login(referee)

        title = await page.title()
        self.logger.debug(f'{referee["name"]}: {title}')

        # Execute the callback function
        await asyncio.sleep(2500 / 1000)
        result = await self.dataDic[type]["read"](page)
        table_outer_html = await result.evaluate("element => element.outerHTML")
        #self.logger.info(f'table_outer_html: {table_outer_html}')
        hText = await self.dataDic[type]["convert"](table_outer_html)
        hText = hText.strip()
        #self.logger.info(f'hText: {hText}')

        if hText:
            if hText != referee[f"last_{type}Text"]:
                self.logger.info(f'{referee["name"]}: NEW UPDATE')
                self.logger.debug(f'{referee["name"]}:B {referee[f"last_{type}Text"]}')
                self.logger.debug(f'{referee["name"]}:A {hText}')
                self.logger.debug(f'{referee["name"]}:Z')
                referee[f"last_{type}Text"] = hText
                referee[f"last_{type}Text_time"] = f'{datetime.now()}'
                await self.writeRefereeText(type, referee)
                await self.dataDic[type]["notify"](referee)
            else:
                self.logger.info(f'{referee["name"]}: No {type} update since {referee[f"last_{type}Text_time"]}...')
                pass
        else:
            pass

    async def login(self, referee):
        try:
            # Navigate to the URL
            self.logger.debug(f'login')
            page = referee['page']
            await page.goto(self.loginUrl)
            await page.wait_for_load_state(state='load', timeout=5000)
            #title = await page.title()
            #self.logger.info(f'{referee["name"]}: {title}')
            
            input_elements = await page.query_selector_all('input')
            
            usernameField = input_elements[0]
            await usernameField.fill(referee["refId"])

            passwordField = input_elements[1]
            await passwordField.fill(referee["refPass"])

            idField = input_elements[2]
            await idField.fill(referee["id"])

            # Find the submit button and click it
            button_elements = await page.query_selector_all('button')
            mainButton = button_elements[0]
            await mainButton.click()  # Replace selector as needed

            await asyncio.sleep(2000 / 1000)

        except Exception as ex:
            if referee["page"]:
                await referee["page"].close()
                referee["page"] = None
            self.logger.error(f'Error2: {ex}')

    async def start(self):
        self.logger.debug('Start')
        browser = None
        context = None

        try:
            async with async_playwright() as p:
    
                browser = await p.chromium.launch(headless=True, args=['--disable-dev-shm-usage','--disable-extensions','--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-software-rasterizer','--verbose'])
                #browser = await p.chromium.launch_persistent_context(user_data_dir='./user-data-dir', headless=True, args=['--disable-dev-shm-usage','--disable-extensions','--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--disable-software-rasterizer','--verbose'])
                context = await browser.new_context()
                self.logger.debug(f'launch')

                for referee in self.referees:
                    referee["last_gamesText_time"] = None
                    referee["last_reviewsText_time"] = None

                while True:
                    try:
                        refereesTasks = []
                        for referee in self.referees:
                            self.logger.debug(f'{type(referee)}')
                            self.logger.debug(f'before if')
                            if 'page' not in referee or referee['page'] == None:
                                # Init Referee
                                self.logger.debug(f'{json.dumps(referee)}')
                                self.logger.debug(f'before new page')
                                page = await context.new_page()
                                await page.wait_for_timeout(5000)
                                referee["page"] = page
                                await self.readRefereeText('games', referee)
                                await self.readRefereeText('reviews', referee)
                                self.logger.debug(f'{referee["name"]}: new page')
                            refereesTasks.append(asyncio.create_task(self.checkReferee(referee)))
                        tasksResults = await asyncio.gather(*refereesTasks)
                    except Exception as ex:
                        self.logger.error(f'Error1: {ex}')
                        pass
                    finally:
                        if self.alwaysClosePage:
                            for referee in self.referees:
                                if referee['page']:
                                    await referee['page'].close()
                                    referee['page'] = None 
                        await asyncio.sleep(self.pollingInterval / 1000)
                        pass

        except Exception as ex:
            self.logger.error(f'Error: {ex}')
            pass
        
        finally:
            self.logger.debug(f'close')
            if browser and context:
                await context.close()
                await browser.close()
            # Disconnect the client
            self.mqttClient.disconnect()
            pass

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