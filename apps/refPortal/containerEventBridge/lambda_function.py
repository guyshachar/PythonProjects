# lambda_function.py
from datetime import datetime, timezone
import sys
import os
from pathlib import Path
import asyncio
import socket
import logging

sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(os.path.join(os.path.dirname(__file__), "packages"))

import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.db import CacheService
from shared.logger import Logger
from shared.db import CacheService
from shared.db import DynamodbClient
from shared.db import RedisClient
from shared.refereeProcessServiceClient import invokeLambdaFunction
from shared.messaging import MessagingService
from shared.handleUsers import HandleUsers
from shared.handleRefereeData import HandleRefereeData

app = os.getenv('app')
env = os.getenv('app_env')
logger:Logger = None
dbClient:DbClientBase = None
messagingService:MessagingService = None
handleUsers:HandleUsers = None
handleRefereeData:HandleRefereeData = None
functionName = f"{os.getenv('awsFunctionName')}_{env}"

refereesPerRun = int(os.getenv('refereesPerRun') or '10')
refereeIntervalInMin:int
assignments:dict = {}

initialized = False

def initialize():    
    #container = Container()
    global initialized
    global logger
    global dbClient
    global messagingService
    global handleUsers
    global handleRefereeData
    global refereeIntervalInMin
    global assignments

    if initialized:
        return
    
    logger = Logger()
    messagingService = MessagingService(logger, dbClient)        

    openText=f'Ref Portal EventBridge {jsonHelper.datetime_to_str(helpers.localNow())} build#{os.getenv("BUILD_DATE")} host={socket.gethostname()}'
    logger.info(openText)

    if os.getenv('db') == 'redis':
        dbClient = RedisClient(env=os.getenv('app_env'), logger=logger, host=os.getenv('redisHost'), port=int(os.getenv('redisPort')), db=int(os.getenv('redisDb')))
    else:
        dbClient = DynamodbClient(env=os.getenv('app_env'), logger=logger, awsRegion=os.getenv('awsRegion'), endpointUrl=os.getenv('dynamoDbEndpointUrl'))
    
    handleUsers = HandleUsers(logger)
    handleRefereeData = HandleRefereeData(logger, dbClient, messagingService, handleUsers)

    assign_digits_to_processGroups()
    
    initialized = True
    
    logger.info(f'RefPortalEventBridge starts...')

def assign_digits_to_processGroups() -> dict:
    '''
    load = 300 -> every 5 mins
    processes = 5
    interval invoke every = 5 / 5 = 1 min
    digits in process = 10 / processes = 2
    subProcess = time.minute % processes
        0 -> 0 -> 0,1
        1 -> 1 -> 2,3
        2 -> 2 -> 4,5
        3 -> 3 -> 6,7
        4 -> 4 -> 8,9

    load = 720 -> every 12 mins
    processes = 4
    interval invoke every = 12 / 4 = 3 mins
    digits in process = 10 / processes = 3
    subProcess = time.minute
        0 -> 0 -> 0,1,2
        3 -> 1 -> 3,4,5
        6 -> 2 -> 6,7,8
        9 -> 3 -> 9
    '''
    global refereeIntervalInMin
    global assignments

    loadInterval = int(os.getenv('loadInterval', '300'))
    processGroups = int(os.getenv('processGroups', '1'))
    refereeIntervalInMin = int(loadInterval / 60)
    invokeServiceInterval:int = int(refereeIntervalInMin / processGroups)
    digitsPerProcess = int(10 / processGroups + 0.5)
    #assignments1 = {}

    runDigit = 0
    digit = 0
    for i in range(processGroups):
        assignments[runDigit] = []
        for j in range(digitsPerProcess):
            assignments[runDigit].append(digit)
            digit += 1
            if digit > 9:
                break
        runDigit += invokeServiceInterval

    logger.info(f'loadInterval={loadInterval} processGroups={processGroups} refereeIntervalInMin={refereeIntervalInMin} invokeServiceInterval={invokeServiceInterval} digitsPerProcess={digitsPerProcess} assignments={assignments}')

def lambda_handler(event, context):
    initialize()
    return asyncio.run(start(event, context))

async def start(event, context):
    logger.debug('Start')
    cnt = 0
    try:
        digitToRun = datetime.now().minute % refereeIntervalInMin
        digits = assignments.get(digitToRun)
        if not digits:
            return
        
        if digitToRun == 0 or len(handleRefereeData.activeRefereeByRefId) == 0:
            handleRefereeData.loadActiveRefereeDetails()

        referees = handleRefereeData.activeRefereeByRefId
        partialReferees = list({refId:referee for refId, referee in referees.items() if int(refId[-1]) in digits}.items())
        cnt = len(partialReferees)
        logger.info(f'digits={digits} #referees={len(partialReferees)}')
        for i in range(0, len(partialReferees), refereesPerRun):
            batchReferees = dict(partialReferees[i : i + refereesPerRun])
            refereeIds = list(batchReferees.keys())
            logger.info(f'Invocing process lambda {functionName} for {len(refereeIds):000} referees...')
            await invokeLambdaFunction(logger=logger, cacheService=cacheService, refereeIds=refereeIds)

        #if generateReports and mainInstance and anyChange:
        #    await handleRefereeData.collectGamesSummary()

    except Exception as ex:
        logger.error(f'start', ex)
    
    finally:
        logger.debug(f'close')

        return {
            'statusCode': 200,
            'message': f'{cnt} processed successfully',
        }

#initialize()

if __name__ == "__main__":
    logging.info('INIT1...')
    initialize()
    logging.info('INIT2...')
    #lambda_handler(None, None)