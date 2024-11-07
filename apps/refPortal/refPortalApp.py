import appdaemon.plugins.hass.hassapi as hass

from Shared.logger import Logger
import logging
import time
import datetime
import json

from playwright.sync_api import sync_playwright

class RefPortalApp(hass.Hass):
#class RefPortalApp():
    def __init__(self):
        self.call_service("mqtt/publish", topic='my/mqtt/refPortal/init', payload=f'now={datetime.datetime.now().timestamp()}', qos=1)

        Logger(self)
        self.logger.info("Ref Portal from AppDaemon")
        
        self.url = self.args['url']
        self.pollingInterval = self.args['polling_interval']
        self.topic = self.args['topic']
        """   
        self.url = 'https://ref.football.org.il/login'
        self.pollingInterval = 5000
        self.topic = 'my/mqtt/refPortal/new'
        """
        self.refId = '43679'
        self.refPass = 'S073XdLR'
        self.id = '025092271'

        self.logger.info(f'url={self.url}')

        pass

    def initialize(self):
        self.start()
        pass

    def login(self):
        with sync_playwright() as p:
            result = ''

            try:
                browser = p.chromium.launch(headless=True)  # Launch browser (headless=True for no UI)
                page = browser.new_page()

                # Navigate to the URL
                page.goto(self.url)  # Replace with your target URL

                title = page.title()
                # Perform actions, e.g., print the title of the page
                print("Page title is:", title)
                
                input_elements = page.query_selector_all('input')
                
                usernameField = input_elements[0]
                usernameField.fill(self.refId)

                passwordField = input_elements[1]
                passwordField.fill(self.refPass)

                idField = input_elements[2]
                idField.fill(self.id)

                # Find the submit button and click it
                button_elements = page.query_selector_all('button')
                mainButton = button_elements[0]
                mainButton.click()  # Replace selector as needed

                page.wait_for_timeout(2000)  # Wait for 2 seconds

                # Execute the callback function
                result = self.readPortal(page)

                pass

            except Exception as ex:
                pass
    
            finally:
                browser.close()
                return result
                pass

    def readPortal(self, page):
        try:
            table_elements = page.query_selector_all('table')
            table_html = table_elements[0].inner_html()
            result = table_html
            pass

        except Exception as ex:
            pass

        finally:        
            # Print page content
            print(page.content())
            return result

    def notifyUpdate(self, result):
        self.logger.debug(f'result: {result}')
        js = json.dumps(result)
        
        try:
            #self.call_service("mqtt/publish", topic=self.topic, payload=json.dumps(result), qos=1)
            pass
        finally:
            pass
    
    def start(self):
        lastResult = ''
        while True:
            timeNow = datetime.datetime.now().timestamp()
            next_run = time.perf_counter() + self.pollingInterval / 1000

            try:
                result = self.login()  # Call the method
                if result:
                    if result != lastResult:
                        lastResult = result
                        self.notifyUpdate(result)
                    else:
                        pass
                else:
                    pass
            except Exception as ex:
                self.logger.error(f'{ex}')

            sleep_duration = next_run - time.perf_counter()
            if sleep_duration > 0:
                self.logger.debug(f'loop {sleep_duration} {time.perf_counter()}')
                time.sleep(sleep_duration)

if __name__ == "__main__":
    #app = RefPortalApp()
    #app.start()
    pass