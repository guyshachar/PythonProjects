import os
import asyncio
from pathlib import Path
import sys
import schedule
import time
import logging
import lambda_function
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers

env = os.getenv('app_env')
loadInterval:int = int(os.getenv('loadInterval', '300'))
subProcesses:int = int(os.getenv('subProcesses', '1'))
access_key = helpers.get_secret('aws_access_key_id')
secret_key = helpers.get_secret('aws_secret_access_key')

subProcess:int = 0

async def run():
    global subProcess
    global subProcesses

    try:
        os.environ['AWS_ACCESS_KEY_ID'] = access_key
        os.environ['AWS_SECRET_ACCESS_KEY'] = secret_key
        os.environ['AWS_DEFAULT_REGION'] = os.getenv('awsRegion')
    except Exception as ex:
        pass

    if loadInterval <= 0:
        subProcesses = 1

    lambda_function.initialize()

    logging.info(f'env={env} loadInterval={loadInterval} subProcesses={subProcesses}')
 
    if loadInterval > 0:
        schedule.every(loadInterval / subProcesses / 60).minutes.at(":00").do(run_async_job)
        while True:
            schedule.run_pending()
            await asyncio.sleep(1)
    else:
        run_async_job()

def run_async_job():
    global subProcess
    logging.info(f'run_async_job@{helpers.localNow()} subProcess={subProcess}')
    context = {'subProcess': subProcess}
    if subProcess < subProcesses - 1:
        subProcess += 1
    else:
        subProcess = 0
    asyncio.create_task(lambda_function.start(event=None, context=context))

if __name__ == "__main__":
    asyncio.run(run())
    logging.info(f'rpEventBridge completed')
