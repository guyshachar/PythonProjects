from abc import ABC, abstractmethod
import json
import asyncio
import os
import sys
import json
import re
from datetime import datetime, timedelta
import boto3
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from shared.logger import Logger
from shared.db import CacheService

class MessagingClientBase(ABC):
    def __init__(self, logger:Logger, cacheService:CacheService, clientName:str, fromMobile:str, useClient:bool):
        try:
            self.logger = logger
            self.cacheService = cacheService
            self.clientName = clientName
            self.fromMobile = fromMobile
            self.useClient = useClient

            self.logger.info(f'{clientName} starts... fromMobile: {fromMobile}, useClient: {useClient}')
        
        except Exception as ex:
            self.logger.error('init', ex)

    #@abstractmethod
    def test(self):
        pass
