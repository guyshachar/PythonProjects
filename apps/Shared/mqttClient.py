import threading
import asyncio

class MqttClient():

    def __init__(self, hass, logger):
        self.hass = hass
        self.logger = logger

        self.logger.info('MqttClient INIT')    

    async def publish(self, topic, payload, qos):
        self.topic = topic
        self.payload = payload
        self.qos = qos

        self.logger.info('MqttClient publish')    
        loop = asyncio.get_running_loop() 
        threading.Thread(target=self.separate_thread, args=[loop]).start()

    def separate_thread(self, loop):
        self.logger.info('MqttClient separate_thread1')    
        asyncio.run_coroutine_threadsafe(self.my_async_func(), loop)
        self.logger.info('MqttClient separate_thread2')    

    async def my_async_func(self):
        self.logger.info('MqttClient my_async_func')    
        await self.hass.call_service("mqtt/publish", topic=self.topic, payload=payload, qos=self.qos)
