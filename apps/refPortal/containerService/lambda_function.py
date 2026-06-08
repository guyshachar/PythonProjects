# lambda_function.py
from datetime import datetime, timezone
import sys
import os
from pathlib import Path
import asyncio
import socket
import uuid

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(os.path.join(os.path.dirname(__file__), "packages"))

import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db import CacheService
from shared.db import DynamodbClient
from shared.db import RedisClient
from shared.logger import Logger
from shared.refereeProcessService import RefereeProcessService
from shared.messaging import MessagingService
from shared.handleUsers import HandleUsers
from shared.handleRefereeData import HandleRefereeData
from shared.handleTournaments import HandleTournaments

app = os.getenv('app')
env = os.getenv('app_env')
logger = None
dbClient:DbClientBase = None
messagingService = None
handleUsers = None
handleTournaments = None
handleRefereeData = None

initialized = False

def initialize():    
    #container = Container()
    global initialized
    global logger
    global dbClient
    global messagingService
    global handleUsers
    global refereesDetails, refereesByMobile, refereesByGuid
    global handleTournaments
    global handleRefereeData

    if initialized:
        return

    #gameDetail = {'gamePk': 'gamePk35345345', 'homeTeamName':'שיכון', 'guestTeamName': 'ותיקים', 'tournamentName': 'ליגה ג'}    
    #groupJpg = helpers.createHebrewTextImage(gameDetail)
    #print(f'groupJpg={groupJpg}')

    logger = Logger()

    openText=f'Ref Portal Service {jsonHelper.datetime_to_str(helpers.localNow())} build#{os.getenv("BUILD_DATE")} host={socket.gethostname()}'
    logger.info(openText)

    if os.getenv('db') == 'redis':
        dbClient = RedisClient(env=os.getenv('app_env'), logger=logger, host=os.getenv('redisHost'), port=int(os.getenv('redisPort')), db=int(os.getenv('redisDb')))
    else:
        dbClient = DynamodbClient(env=os.getenv('app_env'), logger=logger, awsRegion=os.getenv('awsRegion'), endpointUrl=os.getenv('dynamoDbEndpointUrl'))
    
    logger.debug('After dbClient')

    handleUsers = HandleUsers(logger=logger)
    (globalRefereesByMobile, refereesDetails, refereesByMobile, refereesByGuid) = handleUsers.getAllReferees()
    logger.debug('After handleUsers')

    messagingService = MessagingService(logger=logger, cacheService=cacheService, refereesByMobile=refereesByMobile)        
    logger.debug('After messagingService')

    handleTournaments = HandleTournaments(logger=logger, dbClient=dbClient)
    logger.debug('After handleTournaments')
    handleRefereeData = HandleRefereeData(logger=logger, cacheService=cacheService, messagingService=messagingService, handleUsers=handleUsers)

    initialized = True
    
    logger.info(f'RefPortalService starts...')

def lambda_handler(event, context):
    return asyncio.run(start(event, context))

async def start(event, context):
    initialize()

    if not isinstance(event, dict):
        return {
            'statusCode': 400,
            'message': 'Input is in bad format',
            'event': event
        }

    invocationId = event['invocationId']
    refereeIds = event['refereeIds']
    event['startProcessingTime'] = datetime.now(timezone.utc).isoformat()
    dbClient.setInvocation(invocationId, event)

    logger.info(f'start {refereeIds}')
    # Launch the browser with all necessary parameters
    logger.info("Launching browser...")

    handleRefereeData.loadActiveRefereeDetails()
    refereeProcessService = RefereeProcessService(logger, dbClient, messagingService, handleTournaments, handleRefereeData, handleUsers)       
    anyChange =  await refereeProcessService.startProcessByMobileNos(refereeIds)
    event['anyChange'] = anyChange
    event['endProcessingTime'] = datetime.now(timezone.utc).isoformat()
    dbClient.setInvocation(invocationId, event)

    return {
        'statusCode': 200,
        'message': f'{refereeIds} processed successfully',
        'anyChange': anyChange
    }

initialize()

if __name__ == "__main__":
    initialize()
    refereeIds = [ "43679" ]
    payload = { 'invocationId': str(uuid.uuid4()), 'refereeIds': refereeIds }
    dbClient.setInvocation(payload['invocationId'], payload)

    lambda_handler(payload, None)