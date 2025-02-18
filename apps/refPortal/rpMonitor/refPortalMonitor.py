import asyncio
from datetime import datetime, timedelta, timezone
import os
import logging
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.dockerClient import DockerClient
import shared.helpers as helpers

class RefPortalMonitor():
    def __init__(self, logger=None):
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

        self.logger.info('Init Monitoring...')
        self.start_delay = int(os.environ.get('start_delay', '10'))  # Check every 5 seconds
        self.monitor_interval = int(os.environ.get('monitor_interval', '5'))  # Check every 5 seconds

        self.dockerClient = DockerClient(logger)

    async def monitor_service(self, container):
        #container = client.containers.get(container)
        uptime = self.dockerClient.elapsedTime(container.attrs['State']['StartedAt'])

        self.logger.info(f'Monitoring service {container.name} started...')

        if uptime.seconds < self.start_delay:
            logging.warning(f'service {container.name} uptime is {uptime.seconds}')
            return
        
        formattedLogs = await self.dockerClient.getServiceLogs(container)
        for log in formattedLogs:
            try:
                if log['logElapsed'] > self.monitor_interval:
                    logging.error(f'service {container.name}, No logs for {self.monitor_interval} seconds! Restarting container...')
                    self.dockerClient.containerRestart(container)
            except (ValueError, IndexError) as ex:
                helpers.logError(self.logger, f'monitor_service {log}', ex)  # Print unmodified if format is unexpected

    async def main(self):
        self.logger.info('Monitoring started...')
        servicePrefix = os.environ.get('servicePrefix', '')
        while True:
            services = await self.dockerClient.getServices(servicePrefix)
            if len(services) == 0:
                print(f'No services to monitor...')
            else:
                tasks = [asyncio.create_task(self.monitor_service(service)) for service in services]
                await asyncio.gather(*tasks)
            await asyncio.sleep(self.monitor_interval)

if __name__ == '__main__':
    refPortalMonitor = RefPortalMonitor()
    asyncio.run(refPortalMonitor.main())
