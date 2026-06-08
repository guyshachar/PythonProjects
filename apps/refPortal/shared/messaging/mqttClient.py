import paho.mqtt.client as mqtt
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import logging

class MqttClient:
    def __init__(self, env, logger):
        self.env = env
        self.logger = logger

        try:

            self.mqttEnable = eval(os.getenv('mqttEnable', 'False'))

            if self.mqttEnable == False:
                self.logger.debug(f'mqtt: Disabled')
                return
            mqttBroker = helpers.get_secret('mqtt_broker') # Replace with your broker's address
            mqttPort = 1883                   # Typically 1883 for unencrypted, 8883 for encrypted
            self.mqttClient = mqtt.Client()
            logging.getLogger("mqtt").setLevel(logging.WARNING)
            mqtt_username = helpers.get_secret('mqtt_username')
            mqtt_password = helpers.get_secret('mqtt_password')
            self.logger.debug(f'mqtt: {mqttBroker} {mqtt_username}')
            self.mqttClient.username_pw_set(username=mqtt_username, password=mqtt_password)
            self.mqttClient.connect(mqttBroker, mqttPort)

        except Exception as ex:
            self.logger.error(f'mqtt: Error {ex}')
        finally:
            self.logger.debug(f'mqtt: After')

    def publish(self, topic, payload, title = None, refId = None):
        if self.mqttEnable == False:
            return

        try:
            if self.mqttClient:
                message1 = payload
                message1 = message1.replace('"',"'")
                message1 = message1.replace('\n','   ')
                if refId:
                    topic+= f'/{refId}'
                topic = f'{self.env}/{topic}'
                response = self.mqttClient.publish(topic=topic, payload=f'**{title}**\n{message1}',qos=1)
                self.logger.debug(f"Mqtt: Message '{payload:30}' published to topic '{topic}' {response}")

        except Exception as e:
            self.logger.error(f"Mqtt: An error occurred:", e)

    def disconnect(self):
        if self.mqttEnable == False:
            return
        self.mqttClient.disconnect()