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
from shared.logger import Logger

class DockerClient():
    def __init__(self, logger:Logger):
        self.logger = logger
        try:
            self.client = self._get_docker_client()
        except Exception as ex:
            self.logger.error(f'Error in DockerClient init: {ex}', exc_info=True)
            self.client = None

    def _get_docker_client(self):
        """Get Docker client with fallback for different socket locations"""
        # Try default connection first
        try:
            return docker.from_env()
        except docker.errors.DockerException as e:
            if "No such file or directory" in str(e):
                # Try alternative socket paths for different systems
                alternative_paths = [
                    f'unix://{os.path.expanduser("~")}/.docker/run/docker.sock',  # macOS Docker Desktop
                    'unix:///var/run/docker.sock',  # Linux default
                    'npipe:////./pipe/docker_engine',  # Windows
                ]
                
                for socket_path in alternative_paths:
                    try:
                        self.logger.info(f"Trying Docker socket: {socket_path}")
                        client = docker.DockerClient(base_url=socket_path)
                        # Test the connection
                        client.ping()
                        self.logger.info(f"Successfully connected to Docker via {socket_path}")
                        return client
                    except Exception as alt_e:
                        self.logger.debug(f"Failed to connect via {socket_path}: {alt_e}")
                        continue
                
                # If all attempts failed, raise the original error
                self.logger.error("Failed to connect to Docker with any socket path")
                raise e
            else:
                raise e

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
                self.logger.debug(f'last log={logLocalTZ} elapsed={logElapsed.total_seconds()} {logMessage}')

                formattedLogs.append({ 'container': container.short_id, 'nowLocalTZ': nowLocalTZ, 'logElapsed': logElapsed.total_seconds(), 'logMessage': logMessage })
            except (ValueError, IndexError) as ex:
                self.logger.error(f'{log}', ex)  # Print unmodified if format is unexpected

        return formattedLogs

    def elapsedTime(self, datetimeStr):
        datetimeStr = datetime.fromisoformat(datetimeStr.rstrip("Z")).replace(tzinfo=timezone.utc)
        # Convert to Jerusalem time (Asia/Jerusalem)
        localTZ = pytz.timezone(os.getenv('TZ'))
        datetimeLocalTZ = datetimeStr.astimezone(localTZ)
        # Get current time in Jerusalem timezone
        nowJerusalem = datetime.now(localTZ)
        return nowJerusalem -  datetimeLocalTZ

    def containerRestart(self, container):
        return
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
    dockerClient = DockerClient(logging.getLogger(__name__))
    #asyncio.run(dockerClient.main())
