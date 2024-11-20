#import appdaemon.plugins.hass.hassapi as hass

#from Shared.logger import Logger
import logging
import time
import datetime
import json
import os
import asyncio
from playwright.async_api import async_playwright
from twilio.rest import Client
#from html2image import Html2Image
from bs4 import BeautifulSoup
import html2text
import boto3
from botocore.exceptions import ClientError

#from playwright.sync_api import sync_playwright
#from plyer import notification
#from plyer import audio

#class RefPortalApp(hass.Hass):
class RefPortalApp():
    def __init__(self):
        #self.call_service("mqtt/publish", topic='my/mqtt/refPortal/init', payload=f'now={datetime.datetime.now().timestamp()}', qos=1)

        #Logger(self)   
        # Configure logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
     
        self.logger.info("Ref Portal")
        
        self.url = os.environ.get('loadUrl') or 'https://ref.football.org.il/login'
        self.pollingInterval = int(os.environ.get('loadInterval') or '5000')
        self.topic = 'my/mqtt/refPortal/new'
        self.topic = 'my/mqtt/refPortal/new'

        secretName = os.environ.get('refPortalSM') or "refPortal/referees2"
        refPortalSecret = self.get_secret(secretName)
        refereesKey = refPortalSecret and refPortalSecret.get("refPortal_referees", None)

        if refereesKey:
            #self.logger.info(f'refereesSM: {refereesKey}')
            self.referees = json.loads(refereesKey)
        else:
            self.referees = [
            {
                "name": "guy",
                "refId": "43679",
                "refPass": "S073XdLR",
                "id": "025092271",
                "mobile": "+972547799979"
            },
            {
                "name": "erez",
                "refId": "26054",
                "refPass": "26054",
                "id": "031869779",
                "mobile": "+972547799979"
            }
            ]
        self.logger.info(f'Referees#: {len(self.referees)}')
        
        account_sid = refPortalSecret and refPortalSecret.get("twilio_account_sid", None)
        auth_token = refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
        self.twilioClient = Client(account_sid, auth_token)
        self.twilioFromMobile = '+14155238886'
        self.twilioSend = True

        self.logger.info(f'url={self.url} interval={self.pollingInterval}')

        pass

    def get_secret(self, secretName):
        self.logger.info(f'secret: {secretName}')
        region_name = "il-central-1"
        secret = None

        # Create a Secrets Manager client
        session = boto3.session.Session()
        client = session.client(
            service_name='secretsmanager',
            region_name=region_name
        )

        try:
            self.logger.info(f'secret: Get Value')
            get_secret_value_response = client.get_secret_value(
                SecretId=secretName
            )
            self.logger.info(f'secret: Get Value String')
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

    async def readPortal(self, page):
        result = ''
        try:
            self.logger.info(f'before readPortal')
            table_elements = await page.query_selector_all('table')
            if len(table_elements) > 0:
                result = table_elements[0]
            pass

        except Exception as ex:
            self.logger.error(f'readPortal error: {ex}')
            pass

        finally:        
            # Print page content
            #print(page.content())
            return result

    async def convert_table_to_text(self, html):
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

    async def send_notification(self, title, message, fromMobile, toMobile, toName):
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

        message1 = f' שיבוצים של {toName}:' + '\n' + message
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
            sentMessage = self.twilioClient.messages.create(
                from_=f'whatsapp:{fromMobile}',
                to=f'whatsapp:{toMobile}',
                body=f'{message1}'
            )
            self.logger.info(f'message.id: {sentMessage.sid} {sentMessage.status}')

    async def notifyUpdate(self, referee):
        self.logger.info(f'result: {referee["name"]}: {referee["last_hText"]}')
        
        try:
            # Example usage
            await self.send_notification("עדכון שיבוץ בפורטל", referee["last_hText"], self.twilioFromMobile, referee["mobile"], referee["name"])
            #self.call_service("mqtt/publish", topic=self.topic, payload=json.dumps(result), qos=1)
            pass
        finally:
            pass
    
    async def checkReferee(self, referee):
        page = referee["page"]
        await page.reload()
        await page.wait_for_load_state("load")
        self.logger.info(f'url={page.url}')
        input_elements = await page.query_selector_all('input')
        if page.url == 'about:blank' or len(input_elements) >= 3:
            await self.login(referee)
        
        title = await page.title()
        self.logger.info(f'{referee["name"]}: {title}')
        
        # Execute the callback function
        result = await self.readPortal(page)
        table_outer_html = await result.evaluate("element => element.outerHTML")
        #self.logger.info(f'table_outer_html: {table_outer_html}')
        hText = await self.convert_table_to_text(table_outer_html)
        #self.logger.info(f'hText: {hText}')

        if hText:
            if hText != referee["last_hText"]:
                referee["last_hText"] = hText
                await self.notifyUpdate(referee)
            else:
                self.logger.info(f'{referee["name"]}: No update...')
                pass
        else:
            pass

    async def login(self, referee):
        # Navigate to the URL
        self.logger.info(f'login')
        page = referee['page']
        await page.goto(self.url) 
        await page.reload()
        await page.wait_for_load_state("load")
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

        await page.wait_for_timeout(3000)  # Wait for 2 seconds

    async def start(self):
        self.logger.info('Start')
        browser = None
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-setuid-sandbox','--disable-gpu'])
                self.logger.info(f'launch')

                for referee in self.referees:
                    self.logger.info(f'{json.dumps(referee)}')
                    referee["page"] = await browser.new_page()
                    referee["last_hText"] = ''
                    self.logger.info(f'{referee["name"]}: new page')
                    pass

                while True:
                    try:
                        refereesTasks = []
                        for referee in self.referees:
                            refereesTasks.append(asyncio.create_task(self.checkReferee(referee)))
                        tasksResults = await asyncio.gather(*refereesTasks)
                    except Exception as ex:
                        self.logger.error(f'Error: {ex}')
                        pass
                    finally:
                        await asyncio.sleep(self.pollingInterval / 1000)
                        pass

        except Exception as ex:
            self.logger.error(f'Error: {ex}')
            pass
        
        finally:
            self.logger.info(f'close')
            await browser.close()
            pass

if __name__ == "__main__":
    app = RefPortalApp()
    #app.start()
    #asyncio.run(app.start())
    #asyncio.run(app.send_notification("","בוקר טוב",'+14155238886',"+972547961875","ארז"))
    l1 = logging.INFO
    lvl = 'DEBUG1'
    l2 = eval(f'logging.{lvl}')
    print(l1)
    print(l2)
    pass