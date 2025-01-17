import logging
from functools import reduce
import datetime
import json
import asyncio
import time
import os
import socket
from redAlert.src.main import RedAlert
from shared.mqttClient import MqttClient
from shared.httpgetloop import HttpGetLoop
import shared.helpers
from validatenotificationsNew import validateNotifications

class TzevaAdomApp():
    def __init__(self):
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        now = datetime.datetime.now()
        self.openText=f'Tzeva Adom {now.strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")}/{os.environ.get("BUILD_DATE1")} host={socket.gethostname()}'
        self.logger.info(self.openText)

        #self.mqtt = self.get_plugin_api("MQTT")
        self.tzevaadom_raw_topic = os.environ.get('raw_topic')
        self.error_topic = os.environ.get('error_topic')

        self.logger.info("TzevaAdomNew from AppDaemon")
        self.tzevaadom_url = os.environ.get('url')
        self.logger.info(f'{self.tzevaadom_url}')
        self.url_sensor_alerts = os.environ.get('url_sensor_alerts')
        self.logger.info(f'url_sensor_alerts={self.url_sensor_alerts}')
        #self.httpGet = HttpGetLoop(self.tzevaadom_url)

        self.mqttPublish = eval(os.environ.get('mqttPublish') or 'True')
        self.mqttClient = MqttClient(parent=self)
        self.mqttQos = 1
        file=f'{os.environ.get('MY_CONFIG_FILE', '/config/')}{os.environ.get('notify_criteria_file')}'
        self.notifyCriteria = shared.helpers.load_from_json(file)
        notifyDumps = json.dumps(self.notifyCriteria)
        self.logger.warning(notifyDumps)
        file = f"{os.environ.get('MY_HISTORY_FILE', '/history/')}notifyCriteria-{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}"
        self.logger.warning(file)
        shared.helpers.save_to_json(self.notifyCriteria, f'{file}')

        self.usedNotificationIds = list()
        self.lastAlerts = list([{'time':'time1','cities':''},{'time':'time2','cities':''},{'time':'time3','cities':''},{'time':'time4','cities':''},{'time':'time5','cities':''}])
        
        self.loggingInterval = int(os.environ.get('live_logging_interval'))
        self.pollingInterval = int(os.environ.get('polling_interval'))

    async def start(self):
        await self.mqttClient.publish(topic=self.tzevaadom_raw_topic, payload=f"{datetime.datetime.now()}: App Loaded", qos=self.mqttQos, reformat=False)
        #await self.logError('begin start...')
        redAlert = RedAlert()

        while True:
            now = datetime.datetime.now()
            next_run = time.perf_counter() + self.pollingInterval / 1000

            try:
                result = await redAlert.get_red_alerts()
                if False and datetime.datetime.now().second % 5 == 0:
                    result = shared.helpers.load_from_json(f'{os.environ.get('MY_HISTORY_FILE', '/history/')}redAlert-20250101020855.334.json')
                await redAlert.postAlert(result)

                if result:
                    await self.alertCallback(result)
                else:
                    if int(now.timestamp()%5) == 0:
                        msg = "[-] No alerts for now, keep checking ..."
                        self.logger.info(msg)
            except Exception as ex:
                await self.logError(f'{ex}')
            
            await self.postIntervalAction()

            # sleep 1 second after checking alerts over again to not put pressure on the server.
            sleep_duration = next_run - time.perf_counter()
            if sleep_duration > 0:
                self.logger.debug(f'loop {sleep_duration} {time.perf_counter()}')
                await asyncio.sleep(sleep_duration)

    async def terminate(self):
        await self.logError(f'App Terminated')
        await self.mqttClient.publish(topic=self.tzevaadom_raw_topic, payload=f'App Terminated', qos=self.mqttQos, reformat=False)

    async def alertCallback(self, redAlerts):
        self.logger.debug(f'redAlerts: {redAlerts}')
        await self.mqttClient.publish(topic="my/mqtt/tzevaAdom/newAlert", payload=json.dumps(redAlerts), qos=self.mqttQos, reformat=False)
  
        if redAlerts["id"] in self.usedNotificationIds:
            self.logger.debug(f'REPEAT {redAlerts["id"]} {len(self.usedNotificationIds)}')
            return None

        self.usedNotificationIds.append(redAlerts["id"])

        await self.publishAlert(redAlerts)

        for criteria in self.notifyCriteria:
            mappedRedAlerts = validateNotifications(redAlerts, criteria["cities"], self.logger)
            self.logger.debug(f'alertCallback {type(mappedRedAlerts)} {mappedRedAlerts}')
    
            if (mappedRedAlerts and mappedRedAlerts.foundAny):
                await self.actionToTake(mappedRedAlerts, criteria)
                self.logger.debug(f'alertCallback {len(mappedRedAlerts.validatedCities)}')

        now = datetime.datetime.now()
        shared.helpers.save_to_json(redAlerts, f'{os.environ.get('MY_HISTORY_FILE', '/history/')}redAlert-{now.strftime("%Y%m%d%H%M%S")}.{now.microsecond // 1000:03}.json', False)

    async def postIntervalAction(self):
        now = datetime.datetime.now()
        if (now.minute*60 + now.second)%(60*self.loggingInterval) < self.pollingInterval / 1000:
            self.logger.info('service is running...')
            await self.mqttClient.publish(topic=self.tzevaadom_raw_topic, payload=f"{now}: service is running...", qos=self.mqttQos)

    async def setState(self, entityId, state1, attributes1 = None):
        return
    
        self.logger.info(f'trying to set_state {entityId}...')

        if attributes1:
            await self.set_state(entityId, state = state1[:255], attributes = attributes1)
        else:
            await self.set_state(entityId, state = state1[:255])

    async def logError(self, log):
        now = datetime.datetime.now()
        await self.mqttClient.publish(topic=self.error_topic, payload=f"{now}: {log}", qos=self.mqttQos, reformat=False)
        self.logger.error(log)

    async def publishAlert(self, redAlerts):
        self.logger.info(f'publishAlert={redAlerts}')

        await self.setState(self.url_sensor_alerts, f'{redAlerts["id"]}={redAlerts["data"]}')
        
        citiesSorted = sorted(redAlerts["data"])
        self.logger.debug(f'citiesSorted={citiesSorted}')
        if len(citiesSorted) > 0:
            for i in range(len(self.lastAlerts)-1, 0, -1):
                self.lastAlerts[i] = self.lastAlerts[i-1]    
            now = datetime.datetime.now()
            timeNow = now.strftime('%H:%M:%S')
            self.lastAlerts[0] = {'time': timeNow, 'cities': ','.join(citiesSorted)}

        if self.tzevaadom_raw_topic:
            await self.mqttClient.publish(topic=self.tzevaadom_raw_topic, payload=json.dumps(redAlerts), qos=self.mqttQos, reformat=False)

    async def actionToTake(self, mappedRedAlerts, criteria):
        self.logger.debug(f'actionToTake')

        now = datetime.datetime.now()
        try:
            self.logger.info(f'action:{mappedRedAlerts}')
            #foundAny=foundAny, id=redAlerts["id"], timestamp=redAlerts["timestamp"], validatedCities=validatedCitiesPerGroup, title=redAlerts["title"] ,desc=redAlerts["desc"], time_to_run=redAlerts["time_to_run"]))
            if mappedRedAlerts.foundAny and len(mappedRedAlerts.validatedCities) > 0:
                self.logger.info(f'actionToTake1')
                alert = ({"id":mappedRedAlerts.id,
                        "timestamp":mappedRedAlerts.timestamp,
                        "citiesPerGroup":mappedRedAlerts.validatedCities, 
                        "title":mappedRedAlerts.title,
                        "desc":mappedRedAlerts.desc,
                        "time_to_run":mappedRedAlerts.time_to_run
                        })

                if criteria.get("topic"):
                    #self.logger.info(f'{alert}')
                    payload = {"criteria": criteria, "alert": alert}
                    dumpedJson = json.dumps(payload)
                    self.logger.info(dumpedJson)
                    await self.mqttClient.publish(topic=criteria["topic"], payload=dumpedJson, qos=self.mqttQos, reformat=False)

                if criteria.get("sensor"):
                    self.logger.info(f'sensor={criteria["sensor"]} type={type(self.lastAlerts)} {self.lastAlerts}')
                    lastAlertsStr = ','.join(map(lambda a: a['time']+' '+a['cities'], filter(lambda a: a['time'], self.lastAlerts)))
                    #lastAlertsStr = '\r'.join(self.lastAlerts)
                    await self.setState(criteria["sensor"], lastAlertsStr)
                    await self.setState('sensor.tzeva_adom_notification_new1', 
                        self.lastAlerts[0]["time"]+' '+self.lastAlerts[0]["cities"])
                    self.logger.info('sensor updated')
        except NameError:
            await self.logError("Python code is not running inside Home Assistant2.")
        except Exception as e:
            await self.logError(f'ERROR={e}')

if __name__ == "__main__":
    app = None
    try:
        print("Hello Tzeva Adom")
        app = TzevaAdomApp()
        app.logger.info(f'Main run')
        asyncio.run(app.start())
        pass
    except Exception as ex:
        print(f'Main Error: {ex}')
        pass
    