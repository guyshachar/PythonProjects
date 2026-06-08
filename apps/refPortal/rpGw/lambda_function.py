import os
from datetime import datetime
import sys
import os
from pathlib import Path
import asyncio
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(os.path.join(os.path.dirname(__file__), "packages"))

import shared.helpers as helpers
from shared.db import CacheService
from shared.db import DynamodbClient
from shared.logger import Logger
from shared.refereeProcessService import RefereeProcessService
from shared.messaging import MessagingService
from shared.handleUsers import HandleUsers
from shared.handleRefereeData import HandleRefereeData
from shared.handleTournaments import HandleTournaments

app = os.getenv('app')
env = os.getenv('app_env')
logger = Logger()
awsRegion = os.getenv('awsRegion')
dbClient:DbClientBase = DynamodbClient(env=env, logger=logger, awsRegion=awsRegion)
messagingService = MessagingService(logger, dbClient)        
handleUsers = HandleUsers(logger)
handleTournaments = HandleTournaments(logger, dbClient)
handleRefereeData = HandleRefereeData(logger, dbClient, messagingService, handleUsers)

def lambda_handler(event, context):
    try:
        if isinstance(event, list):
            refIds = event
            logger.info(f"processReferees: {refIds}")
            asyncio.run(processReferees(refIds))

            return {
                "statusCode": 200,
                "body": f"Process done"
            }

        else:
            return {
                "statusCode": 400,
                "body": f"Invalid event type"
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": f"Error updating KeyVal: {str(e)}"
        }

async def processReferees(refIds):
    try:
        logger.info(f"processReferees: {refIds}")
        refereeeProcessService = RefereeProcessService(logger=logger, cacheService=cacheService, messagingService=messagingService, handleUsers=handleUsers, handleRefereeData=handleRefereeData, handleTournaments=handleTournaments)   
        refereeTask = asyncio.create_task(refereeeProcessService.startProcessByMobileNos(refIds))
        done, pending = await asyncio.wait([refereeTask], timeout=os.getenv('processTimeout'))
        logger.info(f"processReferees: {refIds} is DONE")
    except Exception as ex:
        logger.error(f"processReferees: {refIds} error:", ex)
