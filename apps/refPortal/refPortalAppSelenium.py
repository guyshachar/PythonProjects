#import appdaemon.plugins.hass.hassapi as hass

from Shared.logger import Logger
import logging
import time
import datetime
import json

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

#class RefPortalApp(hass.Hass):
class RefPortalApp():
    def __init__(self):
        #self.call_service("mqtt/publish", topic='my/mqtt/refPortal/init', payload=f'now={datetime.datetime.now().timestamp()}', qos=1)

        Logger(self)
        self.logger.info("Ref Portal from AppDaemon")
        
        #self.url = self.args['url']
        #self.pollingInterval = self.args['polling_interval']
        #self.topic = self.args['topic']
        self.url = 'https://ref.football.org.il/login'
        self.pollingInterval = 5000
        self.topic = 'my/mqtt/refPortal/new'

        self.logger.info(f'url={self.url}')
 
        self.chrome_options = Options()
        self.chrome_options.add_argument('--headless')
        self.chrome_options.add_argument('--no-sandbox')
        self.chrome_options.add_argument('--disable-gpu')
        self.chrome_options.add_argument('--disable-dev-shm-usage')
        self.chrome_options.add_argument("--whitelisted-ips=")
        #chrome_options.add_argument("--port=5000");
        self.chrome_options.add_argument("--verbose")

        pass

    def initialize(self):
        self.start()
        pass

    def login(self):
        driver = webdriver.Chrome(options=self.chrome_options)

        # URL to navigate to
        result = ''

        try:
            # Open the specified URL
            driver.get(self.url)

            # Perform actions, e.g., print the title of the page
            print("Page title is:", driver.title)
            srv = driver.page_source
            input_fields = driver.find_elements(By.TAG_NAME, 'input')

            usernameField = input_fields[0]
            usernameField.send_keys("43679")

            passwordField = input_fields[1]
            passwordField.send_keys("S073XdLR")

            idField = input_fields[2]
            idField.send_keys("025092271")

            # Find the submit button and click it
            button_tags = driver.find_elements(By.TAG_NAME, 'button')
            submitButton = button_tags[0]
            submitButton.click()

            wait = WebDriverWait(driver, 4)

            # Wait until a specific element i5 present
            wait.until(EC.presence_of_element_located((By.TAG_NAME, 'table')))

            # Execute the callback function
            return self.readPortal(driver)

            pass

        except Exception as ex:
            pass
  
        finally:
            pass

    def readPortal(self, driver):
        try:
            time.sleep(1)
            # Find the submit button and click it
            table_tags = driver.find_elements(By.TAG_NAME, 'table')
            mainTable = table_tags[0]
            result = mainTable.text
            src = driver.page_source
            pass

        except Exception as ex:
            pass

        finally:
            driver.quit()
            return result

    def notifyUpdate(self, result):
        self.logger.debug(f'result: {result}')
        js = json.dumps(result)
        
        try:
            self.call_service("mqtt/publish", topic=self.topic, payload=json.dumps(result), qos=1)
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
    app = RefPortalApp()
    app.start()
    pass