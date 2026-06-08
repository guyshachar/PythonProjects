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

from rpApi.refPortalImplementationFastApi import RefPortalImplementationFastApi
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
refPortalImplementationFastApi = None

initialized = False

def initialize():    
    #container = Container()
    global initialized
    global logger
    global dbClient
    global messagingService
    global handleUsers
    global handleTournaments
    global handleRefereeData
    global refPortalImplementationFastApi

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

    messagingService = MessagingService(logger, dbClient)        
    logger.debug('After messagingService')

    handleUsers = HandleUsers(logger)
    logger.debug('After handleUsers')

    handleTournaments = HandleTournaments(logger, dbClient)
    logger.debug('After handleTournaments')
    handleRefereeData = HandleRefereeData(logger, dbClient, messagingService, handleUsers)

    refPortalImplementationFastApi = RefPortalImplementationFastApi(logger=logger, cacheService=cacheService, messagingService=messagingService)

    initialized = True
    
    logger.info(f'RefPortalService starts...')

def lambda_handler(event, context):
    return asyncio.run(start(event, context))

async def start(event, context):
    initialize()

    if not event or not isinstance(event, dict) or 'Records' not in event:
        return {
            'statusCode': 204,
            'message': 'No records found',
            'event': event
        }

    records = event['Records']
    for record in records:
        request = record['body']
        await refPortalImplementationFastApi.incomingWebhookFromTwilio(request)
        logger.info("SQS Message:", request)

    return {
        'statusCode': 200,
        'message': f'{len(records)} messages processed successfully'
    }

initialize()

if __name__ == "__main__":
    initialize()
    refereeIds = [ "43679" ]
    payload = { 'invocationId': str(uuid.uuid4()), 'refereeIds': refereeIds }
    dbClient.setInvocation(payload['invocationId'], payload)

    lambda_handler(payload, None)