import logging
import appdaemon.plugins.hass.hassapi as hass
from Shared.httpgetloop import HttpGetLoop
from Shared.logger import Logger
from TzevaAdom.validatenotifications import ValidateNotifications
from functools import reduce
import signal
import sys
import datetime
import json
from threading import Event, Thread
import asyncio
import Shared.convert as convert
#from  Shared.mqttClient import MqttClient

class TzevaAdomApp(hass.Hass):
    #tzevaadom_url = "https://api.tzevaadom.co.il/notifications"
    #catcher_url = "https://tzevaadom.requestcatcher.com/test"
    #polling_interval = 2
    #searchForText = ["חולון","גבעתיים"]
    
    def initialize(self):
        Logger(self)
        now = datetime.datetime.now()
        #self.mqtt = self.get_plugin_api("MQTT")
        self.tzevaadom_topic = self.args['topic']

        self.logger.info("TzevaAdom from AppDaemon")
        self.tzevaadom_url = self.args['url']
        self.logger.info(f'{self.tzevaadom_url}')
        self.httpGet = HttpGetLoop(self.tzevaadom_url)

        #self.locationsToValidate = self.args['search_for_text']
        #self.logger.debug(f'{self.locationsToValidate}')

        self.notifyCriteriaArg = self.args['notify_criteria']
        self.logger.info(f'{self.notifyCriteriaArg}')
        
        self.call_service("mqtt/publish", topic=self.tzevaadom_topic, payload=f"{now}: App Loaded", qos=0)
        
        self.notifyCriteria = list()
        for criteria in self.notifyCriteriaArg: 
            self.logger.info(f'{criteria}')
            criteriaDict = convert.listToDictionary(criteria)
            self.notifyCriteria.append(criteriaDict)
            
            self.call_service("mqtt/publish", topic=criteriaDict["topic"], payload=f"{now}: App Loaded", qos=0)

        self.lastNotifications = list(['','',''])
        
        self.logging_interval = self.args['live_logging_interval']
        self.polling_interval = self.args['polling_interval']

        # Create worker thread
        worker = Thread(target=self.httpGet.start, args=(self.polling_interval, self.publishToTopic, ValidateNotifications().validateNotifications, self.actionToTake, self.notifyCriteria, self.postIntervalAction), name="Thread httpGet.start")
        worker.daemon = True
        worker.start()
        self.event = Event()

    def terminate(self):
        self.logger.error(f'App Terminated')
        self.call_service("mqtt/publish", topic=self.tzevaadom_topic, payload=f'App Terminated', qos=0)
        self.event.clear()
        self.event.wait()

    def postIntervalAction(self):
        now = datetime.datetime.now()
        if (now.minute*60 + now.second)%(60*self.logging_interval) < self.polling_interval / 1000:
            self.logger.info('service is running...')
            self.call_service("mqtt/publish", topic=self.tzevaadom_topic, payload=f"{now}: service is running...", qos=0)

    def publishToTopic(self, notificationsList):
        self.logger.debug(f'publishToTopic={len(notificationsList)}')
        if notificationsList and len(notificationsList) > 0:
            citiesLists = list(map(lambda n: n["cities"], notificationsList))
            citiesList = sorted(list(set([c for n in citiesLists for c in n])))
            self.logger.debug(f'citiesList={citiesList}')
            if len(citiesList) > 0:
                self.lastNotifications[2] = self.lastNotifications[1]
                self.lastNotifications[1] = self.lastNotifications[0]
                now = datetime.datetime.now()
                timeNow = now.strftime('%H:%M:%S')
                self.lastNotifications[0] = f"{timeNow}: {','.join(citiesList)}"

            self.logger.debug(f'PublishToTopic={notificationsList}')
            self.call_service("mqtt/publish", topic=self.tzevaadom_topic, payload=json.dumps(notificationsList), qos=0)

    def actionToTake(self, result, criteria):
        now = datetime.datetime.now()
        try:
            # Check if the 'hass' global object is available
            if hass:
                if result.foundAny and len(result.validatedNotificationsPerGroup) > 0:
                    notifications = list()
                    for vc_group in result.validatedNotificationsPerGroup:
                        self.logger.debug(f'XX1={vc_group}')
                        notificationIds = ','.join(list(set(map(lambda n: n.notificationId, vc_group))))
                        self.logger.debug(notificationIds)
                        times = ','.join(list(set(map(lambda n: str(n.time), vc_group))))
                        self.logger.debug(times)
                        self.logger.debug(f'XX2={vc_group}')
                        citiesLists = list(map(lambda n: n.cities, vc_group))
                        self.logger.debug(f'XX3={citiesLists}')
                        citiesList = sorted(list(set([c for n in citiesLists for c in n])))
                        self.logger.debug(f'XX4={citiesList}')
                        citiesStr = ','.join(citiesList)
                        self.logger.debug(f'XX5={citiesStr}')
                        notifications.append({'notificationIds':notificationIds,
                                            'times':times,
                                            'cities':citiesStr, 
                                            'citiesCount':len(citiesList)})

                    stateId = ','.join(result.notificationIds)
                    self.logger.debug(stateId)
  
                    if criteria and criteria["topic"]:
                        payload = {"criteria": criteria, "notifications": notifications}
                        dumpedJson = json.dumps(payload)
                        self.logger.debug(dumpedJson)
                        self.call_service("mqtt/publish", topic=criteria["topic"], payload=dumpedJson, qos=0)

                    if notifications[0]["cities"] or notifications[1]["cities"] or notifications[2]["cities"]:
                        if criteria and criteria["sensor"]:
                            lastNotoficationStr = '\r'.join(self.lastNotifications)
                            self.set_state(criteria["sensor"], state = lastNotoficationStr)
            else:
                self.logger.error("Python code is not running inside Home Assistant1.")
        except NameError:
            self.logger.error("Python code is not running inside Home Assistant2.")
        except Exception as e:
            self.logger.error(f'ERROR={e}')
