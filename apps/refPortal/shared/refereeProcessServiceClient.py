import os
import uuid
import sys
import json
import boto3
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.path.append(os.path.join(os.path.dirname(__file__), "packages"))
from shared.db import CacheService
from shared.logger import Logger

async def invokeLambdaFunction(logger:Logger, cacheService:CacheService, refereeIds:list) -> bool:
    try:
        # Invoke the Lambda function
        functionName = os.getenv('awsFunctionName')
        if not functionName:
            logger.warning(f'No awsFunctionName env variable')
            return False
        
        env = os.getenv('app_env')
        invocationId = str(uuid.uuid4())
        payload = { 'invocationId': invocationId, 'refereeIds': refereeIds }

        boto3lambdaClient = boto3.client('lambda')
        response = boto3lambdaClient.invoke(
            FunctionName=f'{functionName}_{env}',
            #InvocationType='RequestResponse',  # Synchronous invocation
            InvocationType='Event',  # Asynchronous invocation
            Payload=json.dumps(payload)
        )
        payload['target'] = functionName
        payload['requestId'] = response['ResponseMetadata']['RequestId']

        cacheService.setInvocation(invocationId, payload)
        return True

    except Exception as ex:
        logger.error(f'Error invoking lambda function', ex)