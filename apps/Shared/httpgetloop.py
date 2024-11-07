import requests
import time
from logger import Logger
import json

class HttpGetLoop:
    def __init__(self, url):
        self.url = url
        self.usedNotificationIds = list()
        self.cancel = False
        Logger(self)

    def performHttpGet(self):
        try:
            self.logger.debug(self.url)
            response = requests.get(self.url)
            self.logger.debug(response.status_code)
            response.raise_for_status()
            self.logger.debug(f'HTTP GET successful! Response: {response.text}')
            return response.text
        except requests.exceptions.HTTPError as errh:
            self.logger.error(f'HTTP Error: {errh}')
        except requests.exceptions.ConnectionError as errc:
            self.logger.error(f'Error Connecting: {errc}')
        except requests.exceptions.Timeout as errt:
            self.logger.error(f'Timeout Error: {errt}')
        except requests.exceptions.RequestException as err:
            self.logger.error(f'Request Exception: {err}')
        except:
            self.logger.error('Request Other Exception:')
        finally:
            self.logger.debug('Request finally')

    def cancelProcess(self):
        self.cancel = True
        self.logger.info('Process Cancelled')
            
    def start(self, polling_interval, postGet, criteriaCheck, criteriaAction, notifyCriteria, postIntervalAction):
        while True:#(not self.cancel) or (self.cancel == False):
            try:
                next_run = time.perf_counter() + polling_interval / 1000
    
                response = self.performHttpGet()
                #response = '[{"notificationId":"3271994b-a479-4a9b-99c1-d0d69f4d73d6","time":1697220188,"threat":0,"isDrill":false,"cities":["בני ברק","גבע4תיים","רמת6 גן"]},{"notificationId":"67923996-bc4e-4ce5-bb72-e758028185cb","time":1697220240,"threat":0,"isDrill":false,"cities":["גבע3תיים","תל6אביב"]}]'
    
                self.logger.debug(response)
    
                if response:
                    notificationsJson = json.loads(response)
                    notificationsList = list()
                    for notification in notificationsJson:
                        if notification["notificationId"] in self.usedNotificationIds:
                            self.logger.debug(f'REPEAT {notification["notificationId"]} {len(self.usedNotificationIds)}')
                            continue
                        self.usedNotificationIds.append(notification["notificationId"])
                        notificationsList.append(notification)
                        self.logger.info(f'{notification}')
        
                    if notificationsList and len(notificationsList) > 0:
                        if postGet:
                            postGet(notificationsList)
                        
                        for criteria in notifyCriteria:
                            result = criteriaCheck(notificationsList, criteria["cities"])
                            self.logger.debug(f'performHttpGet1 {type(result)} {result}')
                    
                            if (result and result.foundAny and criteriaAction):
                                criteriaAction(result, criteria)
                                self.logger.debug(f'performHttpGet2 {len(result.validatedNotificationsPerGroup)}')
            except Exception as e:
                self.logger.error(f'Exception in loop: {e}')
    
            if (postIntervalAction):
                postIntervalAction()

            sleep_duration = next_run - time.perf_counter()
            if sleep_duration > 0:
                self.logger.debug(f'loop {sleep_duration} {time.perf_counter()}')
                time.sleep(sleep_duration)

            #break
