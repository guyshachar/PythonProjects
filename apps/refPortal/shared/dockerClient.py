import docker
import asyncio
from datetime import datetime, timedelta, timezone
import os
import logging
import pytz
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers

class DockerClient():
    def __init__(self, logger):
        if logger:
            self.logger = logger
        else:            
            # Configure logging
            logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
            logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            self.logger = logging.getLogger(__name__)        

        self.client = docker.from_env()

    async def getServiceLogs(self, container, tail=1):
        target_tz = pytz.timezone("Asia/Jerusalem")  # Change to your desired timezone
        uptime = self.elapsedTime(container.attrs['State']['StartedAt'])
        
        logs = [log for log in container.logs(tail=tail, timestamps=True).decode().split('\n') if log]
        formattedLogs = []
        for log in logs:
            logTimestamp = log[:log.index(' ')]
            logMessage = log[log.index(' ')+1:]
            try:
                logUtcTZ = datetime.fromisoformat(logTimestamp.rstrip("Z"))
                logLocalTZ = logUtcTZ.replace(tzinfo=pytz.utc).astimezone(target_tz)
                nowLocalTZ = datetime.now(target_tz)
                logElapsed = nowLocalTZ - logLocalTZ
                self.logger.debug(f'last log={logLocalTZ} elapsed={logElapsed.seconds} {logMessage}')

                formattedLogs.append({ 'nowLocalTZ': nowLocalTZ, 'logElapsed': logElapsed.seconds, 'logMessage': logMessage })
            except (ValueError, IndexError) as ex:
                helpers.logError(f'{log} {ex}')  # Print unmodified if format is unexpected

        return formattedLogs

    def elapsedTime(self, datetimeStr):
        datetimeStr = datetime.fromisoformat(datetimeStr.rstrip("Z")).replace(tzinfo=timezone.utc)
        # Convert to Jerusalem time (Asia/Jerusalem)
        localTZ = pytz.timezone(os.environ.get('TZ'))
        datetimeLocalTZ = datetimeStr.astimezone(localTZ)
        # Get current time in Jerusalem timezone
        nowJerusalem = datetime.now(localTZ)
        return nowJerusalem -  datetimeLocalTZ

    def containerRestart(self, container):
        container_info = container.attrs
        image = container_info['Config']['Image']
        name = container_info['Name'].strip("/")  # Remove leading "/"
        env_vars = container_info['Config']['Env']
        ports = container_info['HostConfig']['PortBindings']
        volumes = container_info['Mounts']
        tty = container_info['Config']['Tty']
        restart_policy = container_info['HostConfig']['RestartPolicy']
        detach = container_info['Config']['AttachStdout']  # Keep in detached mode

        # Convert volumes to correct format
        volume_binds = {vol['Source']: {'bind': vol['Destination'], 'mode': vol['Mode']} for vol in volumes}
        secret_files = {vol['Destination']: {'bind': vol['Destination'], 'mode': 'ro'}
                        for vol in volumes if "/run/secrets/" in vol['Destination']}
        
        container.stop()
        container.remove()
        result = self.client.containers.run(
            image=image,
            name=name,
            detach=True,
            tty=tty,
            environment=env_vars,
            ports=ports,
            volumes={**volume_binds, **secret_files},  # Attach secrets & volumes
            restart_policy=restart_policy
        )
        self.logger.info(f'result={result}')

    async def getServices(self, servicePrefix):
        services = [container for container in self.client.containers.list() if servicePrefix in container.name]
        return services

if __name__ == "__main__":
    dockerClient = DockerClient()
    asyncio.run(dockerClient.main())
