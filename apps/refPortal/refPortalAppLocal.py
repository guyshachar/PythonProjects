#import appdaemon.plugins.hass.hassapi as hass

#from Shared.logger import Logger
import logging
import time
import datetime
import json

import asyncio
from playwright.async_api import async_playwright

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
     
        self.logger.info("Ref Portal from AppDaemon")
        
        """   
        self.url = self.args['url']
        self.pollingInterval = self.args['polling_interval']
        self.topic = self.args['topic']
        """   
        self.url = 'https://ref.football.org.il/login'
        self.pollingInterval = 5000
        self.topic = 'my/mqtt/refPortal/new'

        self.refId = '43679'
        self.refPass = 'S073XdLR'
        self.id = '025092271'

        self.logger.info(f'url={self.url}')

        pass

    def initialize(self):
        self.start()
        pass

    async def login(self):
        async with async_playwright() as p:
            self.logger.info(f'login')
            result = ''

            try:
                #browser1 = await p.chromium.launch(headless=True)  # Launch browser (headless=True for no UI)
                browser = await p.chromium.launch(headless=True, args=['--no-sandbox','--disable-setuid-sandbox','--disable-gpu','--single-process'])
                self.logger.info(f'launch')
                page = await browser.new_page()
                self.logger.info(f'new page')
                # Navigate to the URL
                await page.goto(self.url)  # Replace with your target URL
                self.logger.info(f'goto {self.url}')

                title = await page.title()
                self.logger.info(f'{title}')
                # Perform actions, e.g., print the title of the page
                # print("Page title is:", title)
                
                input_elements = await page.query_selector_all('input')
                
                usernameField = input_elements[0]
                await usernameField.fill(self.refId)

                passwordField = input_elements[1]
                await passwordField.fill(self.refPass)

                idField = input_elements[2]
                await idField.fill(self.id)

                # Find the submit button and click it
                button_elements = await page.query_selector_all('button')
                mainButton = button_elements[0]
                await mainButton.click()  # Replace selector as needed

                await page.wait_for_timeout(3000)  # Wait for 2 seconds

                # Execute the callback function
                result = await self.readPortal(page)

                pass

            except Exception as ex:
                self.logger.info(f'Error: {ex}')
                self.logger.error(f'Error: {ex}')
                pass
    
            finally:
                self.logger.info(f'close')
                await browser.close()
                return result
                pass

    async def readPortal(self, page):
        try:
            self.logger.info(f'before readPortal')
            table_elements = await page.query_selector_all('table')
            table_html = await table_elements[0].inner_html()
            table_text = await table_elements[0].inner_text()
            result = table_text
            pass

        except Exception as ex:
            pass

        finally:        
            # Print page content
            #print(page.content())
            return result

    def send_notification(self, title, message):
        #audio.play('')

        notification.notify(
            title=title,
            message=message,
            timeout=15,  # Time in seconds to display the notification
            ticker=title
        )

    def notifyUpdate(self, result):
        self.logger.info(f'result: {result}')
        js = json.dumps(result)
        
        try:
            # Example usage
            #self.send_notification("עדכון שיבוץ בפורטל", result)
            #self.call_service("mqtt/publish", topic=self.topic, payload=json.dumps(result), qos=1)
            pass
        finally:
            pass
    
    async def start(self):
        self.logger.info('Start')
        lastResult = ''
        while True:
            try:
                result = await self.login()  # Call the method
                if result:
                    if result != lastResult:
                        lastResult = result
                        self.notifyUpdate(result)
                    else:
                        self.logger.info(f'No update...')
                        pass
                else:
                    pass
            except Exception as ex:
                self.logger.error(f'{ex}')

            await asyncio.sleep(self.pollingInterval / 1000)

if __name__ == "__main__":
    app = RefPortalApp()
    #app.start()
    asyncio.run(app.start())
    pass