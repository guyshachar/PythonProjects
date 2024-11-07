import appdaemon.plugins.hass.hassapi as hass
#from Shared.httpgetloop import HttpGetLoop
from Shared.logger import Logger
from TzevaAdom.validatenotificationsNew import validateNotifications
from functools import reduce
from redAlert.src.main import RedAlert
import datetime
import json
from threading import Event, Thread
import asyncio
import Shared.convert as convert
import time
#from  Shared.mqttClient import MqttClient

class TzevaAdomAppNew(hass.Hass):

    def initialize(self):
        Logger(self)
        now = datetime.datetime.now()
        #self.mqtt = self.get_plugin_api("MQTT")
        self.tzevaadom_raw_topic = self.args['raw_topic']
        self.error_topic = self.args['error_topic']

        self.logger.info("TzevaAdomNew from AppDaemon")
        self.tzevaadom_url = self.args['url']
        self.logger.info(f'{self.tzevaadom_url}')
        self.url_sensor_alerts = self.args['url_sensor_alerts']
        self.logger.info(f'url_sensor_alerts={self.url_sensor_alerts}')
        #self.httpGet = HttpGetLoop(self.tzevaadom_url)

        self.notifyCriteriaArg = self.args['notify_criteria']
        self.logger.info(f'{self.notifyCriteriaArg}')
        
        self.call_service("mqtt/publish", topic=self.tzevaadom_raw_topic, payload=f"{now}: App Loaded", qos=0)
        
        self.notifyCriteria = list()
        for criteria in self.notifyCriteriaArg: 
            self.logger.info(f'{criteria}')
            criteriaDict = convert.listToDictionary(criteria)
            self.notifyCriteria.append(criteriaDict)
            
            self.call_service("mqtt/publish", topic=criteriaDict["topic"], payload=f"{now}: App Loaded", qos=0)

        self.usedNotificationIds = list()
        self.lastAlerts = list([{'time':'time1','cities':''},{'time':'time2','cities':''},{'time':'time3','cities':''},{'time':'time4','cities':''},{'time':'time5','cities':''}])
        
        self.loggingInterval = self.args['live_logging_interval']
        self.pollingInterval = self.args['polling_interval']

        # Create worker thread
        worker = Thread(target=self.start, args=(), name="Thread red-alert.run")
        worker.daemon = True
        worker.start()
        self.event = Event()

    def start(self):
        self.logError('begin start...')
        redAlert = RedAlert()

        while True:
            timeNow = datetime.datetime.now().timestamp()
            next_run = time.perf_counter() + self.pollingInterval / 1000

            try:
                result = redAlert.run(self.logger)
                if result:
                    self.alertCallback(result)
                else:
                    if int(timeNow%5) == 0:
                        msg = "[-] No alerts for now, keep checking ..."
                        self.logger.info(msg)
            except Exception as ex:
                self.logError(f'{ex}')
            
            self.postIntervalAction()

            # sleep 1 second after checking alerts over again to not put pressure on the server.
            sleep_duration = next_run - time.perf_counter()
            if sleep_duration > 0:
                self.logger.debug(f'loop {sleep_duration} {time.perf_counter()}')
                time.sleep(sleep_duration)

    def terminate(self):
        self.logError(f'App Terminated')
        self.call_service("mqtt/publish", topic=self.tzevaadom_raw_topic, payload=f'App Terminated', qos=0)
        self.event.clear()
        self.event.wait()

    def alertCallback(self, redAlerts):
        self.logger.debug(f'redAlerts: {redAlerts}')
        self.call_service("mqtt/publish", topic="my/mqtt/tzevaAdomNew/newAlert", payload=json.dumps(redAlerts), qos=1)
  
        if redAlerts["id"] in self.usedNotificationIds:
            self.logger.debug(f'REPEAT {redAlerts["id"]} {len(self.usedNotificationIds)}')
            return None

        self.usedNotificationIds.append(redAlerts["id"])

        self.publishAlert(redAlerts)

        for criteria in self.notifyCriteria:
            mappedRedAlerts = validateNotifications(redAlerts, criteria["cities"], self.logger)
            self.logger.debug(f'alertCallback {type(mappedRedAlerts)} {mappedRedAlerts}')
    
            if (mappedRedAlerts and mappedRedAlerts.foundAny):
                self.actionToTake(mappedRedAlerts, criteria)
                self.logger.debug(f'alertCallback {len(mappedRedAlerts.validatedCities)}')

    def postIntervalAction(self):
        now = datetime.datetime.now()
        if (now.minute*60 + now.second)%(60*self.loggingInterval) < self.pollingInterval / 1000:
            self.logger.info('service is running...')
            self.call_service("mqtt/publish", topic=self.tzevaadom_raw_topic, payload=f"{now}: service is running...", qos=0)

    def setState(self, entityId, state1, attributes1 = None):
        self.logger.info(f'trying to set_state {entityId}...')

        if attributes1:
            self.set_state(entityId, state = state1[:255], attributes = attributes1)
        else:
            self.set_state(entityId, state = state1[:255])

    def logError(self, log):
        now = datetime.datetime.now()
        self.call_service("mqtt/publish", topic=self.error_topic, payload=f"{now}: {log}", qos=1)
        self.logger.error(log)

    def publishAlert(self, redAlerts):
        self.logger.info(f'publishAlert={redAlerts}')

        self.setState(self.url_sensor_alerts, f'{redAlerts["id"]}={redAlerts["data"]}')
        
        citiesSorted = sorted(redAlerts["data"])
        self.logger.debug(f'citiesSorted={citiesSorted}')
        if len(citiesSorted) > 0:
            for i in range(len(self.lastAlerts)-1, 0, -1):
                self.lastAlerts[i] = self.lastAlerts[i-1]    
            now = datetime.datetime.now()
            timeNow = now.strftime('%H:%M:%S')
            self.lastAlerts[0] = {'time': timeNow, 'cities': ','.join(citiesSorted)}

        if self.tzevaadom_raw_topic:
            self.call_service("mqtt/publish", topic=self.tzevaadom_raw_topic, payload=json.dumps(redAlerts), qos=0)

    def actionToTake(self, mappedRedAlerts, criteria):
        self.logger.debug(f'actionToTake')

        now = datetime.datetime.now()
        try:
            # Check if the 'hass' global object is available
            if hass:
                self.logger.info(f'action:{mappedRedAlerts}')
                #foundAny=foundAny, id=redAlerts["id"], timestamp=redAlerts["timestamp"], validatedCities=validatedCitiesPerGroup, title=redAlerts["title"] ,desc=redAlerts["desc"], time_to_run=redAlerts["time_to_run"]))
                if mappedRedAlerts.foundAny and len(mappedRedAlerts.validatedCities) > 0:
                    self.logger.info(f'actionToTake1')
                    alert = ({'id':mappedRedAlerts.id,
                            'timestamp':mappedRedAlerts.timestamp,
                            'citiesPerGroup':mappedRedAlerts.validatedCities, 
                            'title':mappedRedAlerts.title,
                            'desc':mappedRedAlerts.desc,
                            'time_to_run':mappedRedAlerts.time_to_run
                            })

                    if criteria and criteria["topic"]:
                        self.logger.info(f'{alert}')
                        payload = {"criteria": criteria, "alert": alert}
                        dumpedJson = json.dumps(payload)
                        self.logger.debug(dumpedJson)
                        self.call_service("mqtt/publish", topic=criteria["topic"], payload=dumpedJson, qos=0)

                    if criteria and criteria["sensor"]:
                        self.logger.info(f'sensor={criteria["sensor"]} type={type(self.lastAlerts)} {self.lastAlerts}')
                        lastAlertsStr = ','.join(map(lambda a: a['time']+' '+a['cities'], filter(lambda a: a['time'], self.lastAlerts)))
                        #lastAlertsStr = '\r'.join(self.lastAlerts)
                        self.setState(criteria["sensor"], lastAlertsStr)
                        self.setState('sensor.tzeva_adom_notification_new1', 
                            self.lastAlerts[0]["time"]+' '+self.lastAlerts[0]["cities"])
                        self.logger.info('sensor updated')
            else:
                self.logError("Python code is not running inside Home Assistant1.")
        except NameError:
            self.logError("Python code is not running inside Home Assistant2.")
        except Exception as e:
            self.logError(f'ERROR={e}')
