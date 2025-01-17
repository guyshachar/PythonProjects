import paho.mqtt.client as mqtt
import logging
import shared.helpers

class MqttClient:
    def __init__(self, parent=None):
        if parent:
            self.logger = parent.logger
        else:
            self.logger = logging.getLogger(__name__)

        try:
            mqttBroker = shared.helpers.get_secret('mqtt_broker') # Replace with your broker's address
            mqttPort = 1883                   # Typically 1883 for unencrypted, 8883 for encrypted
            self.mqttClient = mqtt.Client()
            logging.getLogger("mqtt").setLevel(logging.WARNING)
            mqtt_username = shared.helpers.get_secret('mqtt_username')
            mqtt_password = shared.helpers.get_secret('mqtt_password')
            self.logger.debug(f'mqtt: {mqttBroker} {mqtt_username}/{mqtt_password}')
            self.mqttClient.username_pw_set(username=mqtt_username, password=mqtt_password)
            self.mqttClient.connect(mqttBroker, mqttPort)
        except Exception as e:
            pass
        finally:
            pass

    async def publish(self, topic, payload, title = None, id = None, qos = 0, reformat = True):
        try:
            if self.mqttClient:
                message1 = payload
                if reformat:
                    message1 = message1.replace('"',"'")
                    message1 = message1.replace('\n','   ')
                    if id:
                        topic+= f'/{id}'
                    if title:
                        message1 = f'**{title}**\n{message1}'
                response = self.mqttClient.publish(topic=topic, payload=message1, qos=qos)
                self.logger.debug(f"Mqtt: Message '{payload:30}' published to topic '{topic}' {response}")

        except Exception as e:
            self.logger.error(f"Mqtt: An error occurred: {e}")

    def disconnect(self):
        self.mqttClient.disconnect()