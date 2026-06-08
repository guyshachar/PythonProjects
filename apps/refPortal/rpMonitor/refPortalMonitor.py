import asyncio
from datetime import datetime, timedelta, timezone
import os
import logging
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.dockerClient import DockerClient
import shared.helpers as helpers
from shared.logger import Logger

class RefPortalMonitor():
    def __init__(self):
        # Configure logging
        self.logger = Logger()
        self.logger.info('Init Monitoring...')
        self.start_delay = int(os.getenv('start_delay', '10'))  # Check every 5 seconds
        self.monitor_interval = int(os.getenv('monitor_interval', '5'))  # Check every 5 seconds

        self.dockerClient = DockerClient(self.logger)

    async def monitor_service(self, container):
        #container = client.containers.get(container)
        uptime = self.dockerClient.elapsedTime(container.attrs['State']['StartedAt'])

        self.logger.info(f'Monitoring service {container.name} started...')

        if uptime.total_seconds() < self.start_delay:
            self.logger.warning(f'service {container.name} uptime is {uptime.total_seconds()}')
            return
        
        formattedLogs = await self.dockerClient.getServiceLogs(container)
        for log in formattedLogs:
            try:
                if log['logElapsed'] > self.monitor_interval:
                    self.logger.error(f'service {container.name}, No logs for {self.monitor_interval} seconds! Restarting container...')
                    self.dockerClient.containerRestart(container)
            except (ValueError, IndexError) as ex:
                self.logger.error(f'monitor_service {log}', ex)  # Print unmodified if format is unexpected

    async def main(self):
        self.logger.info('Monitoring started...')
        servicePrefix = os.getenv('servicePrefix', '')
        while True:
            services = await self.dockerClient.getServices(servicePrefix)
            if len(services) == 0:
                self.logger.info(f'No services to monitor...')
            else:
                tasks = [asyncio.create_task(self.monitor_service(service)) for service in services]
                await asyncio.gather(*tasks)
            await asyncio.sleep(self.monitor_interval)

if __name__ == '__main__':
    refPortalMonitor = RefPortalMonitor()
    asyncio.run(refPortalMonitor.main())
