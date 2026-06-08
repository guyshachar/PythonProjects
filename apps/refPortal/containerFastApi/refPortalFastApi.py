from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum
from pydantic import BaseModel
#from dependency_injector import containers, providers
import pandas as pd
import sys
import socket
import os
import time
import boto3
from pathlib import Path
# Add the rpService directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from rpApi.refPortalImplementationFastApi import RefPortalImplementationFastApi, AuthMiddleware
from shared.logger import Logger
from shared.messaging import MessagingService
import shared.helpers as helpers
from shared.db import RedisClient
from shared.db import DynamodbClient
from shared.db import CacheService
from shared.handleUsers import HandleUsers

# Import chat API router
try:
    from .chat_api import chat_router
except ImportError:
    # If running in production, try absolute import
    try:
        from chat_api import chat_router
    except ImportError:
        chat_router = None

class RefPortalFastApi():
    def __init__(self):
        # Configure logging
        if not helpers.isRunningInLambda():
            access_key = helpers.get_secret('aws_access_key_id')
            secret_key = helpers.get_secret('aws_secret_access_key')
            try:
                os.environ['AWS_ACCESS_KEY_ID'] = access_key
                os.environ['AWS_SECRET_ACCESS_KEY'] = secret_key
                os.environ['AWS_DEFAULT_REGION'] = os.getenv('awsRegion')
            except Exception as ex:
                pass

        if eval(os.getenv('overrideLambda', 'False')):
            os.environ['AWS_LAMBDA_FUNCTION_NAME'] = 'YES'

        self.logger = Logger()
        self.env = os.getenv('app_env')
    
        if os.getenv('db') == 'redis':
            self.dbClient:DbClientBase = RedisClient(env=os.getenv('app_env'), logger=self.logger, host=os.getenv('redisHost'), port=int(os.getenv('redisPort')), db=int(os.getenv('redisDb')))
        else:
            self.dbClient:DbClientBase = DynamodbClient(env=os.getenv('app_env'), logger=self.logger, awsRegion=os.getenv('awsRegion'), endpointUrl=os.getenv('dynamoDbEndpointUrl'))
        
        self.incomingApiGuid = helpers.get_secret('incoming_api_guid')

        handleUsers = HandleUsers(logger=self.logger)
        (globalRefereesByMobile, refereesByRefId, refereesByMobile, refereesByGuid) = handleUsers.getAllReferees()

        self.messagingService = MessagingService(logger=self.logger, dbClient=self.dbClient, refereesByMobile=refereesByMobile)        
        self.messagingService.useGreenApi = self.messagingService.useGreenApi \
            and self.messagingService.greenApiClient.getStateInstance().get('stateInstance') == 'authorized'

        openText=f'Ref Portal FastApi {helpers.localNow().strftime("%Y-%m-%d %H:%M:%S")} build#{os.getenv("BUILD_DATE")} host={socket.gethostname()}'
        self.logger.info(openText)
        
        self.app = FastAPI(root_path="/prod")  # 👈 Add this

        # Configure CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # In production, restrict this to specific domains
            allow_credentials=True,
            allow_methods=["*"],  # Allows all HTTP methods including OPTIONS
            allow_headers=["*"],  # Allows all headers
        )

        self.refPortalImplementationFastApi = RefPortalImplementationFastApi(logger=self.logger, dbClient=self.dbClient, messagingService=self.messagingService)

        self.configureRoutes()
        '''
        self.limiter = Limiter(
            get_remote_address,
            app=self.app,
            default_limits=[f'{os.getenv("limitPerMin")} per minute'],
            storage_uri=f'redis://{os.getenv("redisHost")}:{os.getenv("redisPort")}/{os.getenv("redisDb")}',
            storage_options={"socket_connect_timeout": 30},
            strategy="fixed-window", # or "moving-window" or "sliding-window-counter"
            key_prefix=os.getenv("env")
        )
        '''

    def configureRoutes(self):
        self.app.add_middleware(AuthMiddleware, logger=self.logger)

        #static
        self.app.add_api_route(
            path="/",
            endpoint=self.refPortalImplementationFastApi.root,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/welcome",
            endpoint=self.refPortalImplementationFastApi.welcome,
            methods=["GET"]
        )
        
        #self.app.add_url_rule('/admindashboard', 'dashboard', self.refPortalApiImplementation.dashboard, methods=['GET'])
        #self.app.add_url_rule('/dashboard/<guid>', 'dashboardByRef', self.refPortalApiImplementation.dashboard, methods=['GET'])

        #self.app.add_url_rule('/api/dashboardLoadData', 'dashboardLoadData', self.refPortalApiImplementation.dashboardLoadData, methods=['GET'])
        #self.app.add_url_rule('/api/dashboardLoad', 'dashboardLoad', self.dashboardLoad, methods=['GET'])
        #self.app.add_url_rule('/api/dashboardLoadData/<guid>', 'dashboardForReferee', self.refPortalApiImplementation.dashboardLoadDataForReferee, methods=['GET'])
        #self.app.add_url_rule(rule='/api/dashboardLoadData', endpoint='dashboardLoadData', view_func=cross_origin(origins=["https://www.refereex.com"])(self.dashboardLoadData), methods=['GET'])
        
        #self.app.add_url_rule('/calendar/<guid>', 'calendar', self.refPortalApiImplementation.calendar, methods=['GET'])
        #self.app.add_url_rule('/api/calendar/<guid>', 'loadCalendar', self.refPortalApiImplementation.loadCalendar, methods=['GET'])

        self.app.add_api_route(
            path="/registration",
            endpoint=self.refPortalImplementationFastApi.registration,
            methods=["GET"]
        )
        '''
        self.app.add_url_rule('/refreshLeaguesTables', 'refreshLeaguesTables', self.refreshLeaguesTables, methods=['GET'])
        self.app.add_url_rule('/changePassword', 'changePassword', self.changePassword, methods=['GET'])
        self.app.add_url_rule('/getReferee', 'getReferee', self.getReferee, methods=['GET'])
        self.app.add_url_rule('/addPending', 'addPending', self.addPending, methods=['GET'])
        self.app.add_url_rule('/activate', 'activate', self.activate, methods=['GET'])
        self.app.add_url_rule('/deactivate', 'deactivate', self.deactivate, methods=['GET'])
        '''

        #api
        self.app.add_api_route(
            path="/api/health",
            endpoint=self.refPortalImplementationFastApi.health,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/delay",
            endpoint=self.refPortalImplementationFastApi.delay,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/changePassword",
            endpoint=self.refPortalImplementationFastApi.changePasswordSubmit,
            methods=["POST"]
        )
        #self.app.add_url_rule('/api/reloadReferees', 'reloadReferees', self.refPortalApiImplementation.reloadReferees, methods=['GET'])
        self.app.add_api_route(
            path="/api/refreshLeaguesTables",
            endpoint=self.refPortalImplementationFastApi.refreshLeaguesTablesSubmit,
            methods=["POST"]
        )
        self.app.add_api_route(
            path="/api/approveGame/{refId}/{msgSid}/{gameId}",
            endpoint=self.refPortalImplementationFastApi.approveGame,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/getGameUpdateTemplate/{refId}/{gameId}",
            endpoint=self.refPortalImplementationFastApi.getGameUpdateTemplate,
            methods=["GET"]
        )
        #downloadIcsFileLimit = self.limiter.limit('10 per minute')(self.downloadIcsFile)
        self.app.add_api_route(
            path="/api/file/{fileId}",
            endpoint=self.refPortalImplementationFastApi.downloadIcsFile,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/registration",
            endpoint=self.refPortalImplementationFastApi.registrationSubmit,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/processRefId/{refId}",
            endpoint=self.refPortalImplementationFastApi.processRefId,
            methods=["GET"]
        )
        self.app.add_api_route(
            path="/api/processRefIds",
            endpoint=self.refPortalImplementationFastApi.processRefId,
            methods=["POST"]
        )
        self.app.add_api_route(
            path="/api/processRefIds",
            endpoint=self.refPortalImplementationFastApi.processRefIdsPost,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/login",
            endpoint=self.refPortalImplementationFastApi.login,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/check-auth",
            endpoint=self.refPortalImplementationFastApi.checkAuth,
            methods=["POST"]
        )

        self.app.add_api_route(
            path="/api/logout",
            endpoint=self.refPortalImplementationFastApi.logout,
            methods=["POST"]
        )
        '''
        self.app.add_url_rule('/api/getReferee', 'getRefereeSubmit', self.getRefereeSubmit, methods=['POST'])
        self.app.add_url_rule('/api/addPending', 'addPendingSubmit', self.addPendingSubmit, methods=['POST'])
        self.app.add_url_rule('/api/activate', 'activateSubmit', self.activateSubmit, methods=['POST'])
        self.app.add_url_rule('/api/deactivate', 'deactivateSubmit', self.deactivateSubmit, methods=['POST'])
        '''

        # twilio
        self.app.add_api_route(
            path=f"/twilio/{self.incomingApiGuid}/incomingWebhook",
            endpoint=self.refPortalImplementationFastApi.incomingWebhookFromTwilio,
            methods=["POST"]
        )
        #statusCallBackLimit = self.limiter.exempt()(self.statusCallback)
        self.app.add_api_route(
            path=f"/twilio/{self.incomingApiGuid}/statusCallback",
            endpoint=self.refPortalImplementationFastApi.statusCallback,
            methods=["POST"]
        )

        # greenApi
        self.app.add_api_route(
            path=f"/greenApi/{self.incomingApiGuid}/incomingWebhook",
            endpoint=self.refPortalImplementationFastApi.incomingWebhookFromGreenApi,
            methods=["POST"]
        )

        # manychat
        self.app.add_api_route(
            path=f"/manychat/{self.incomingApiGuid}/incomingWebhook",
            endpoint=self.refPortalImplementationFastApi.incomingWebhookFromManychat,
            methods=["POST"]
        )

        # meta GET
        self.app.add_api_route(
            path=f"/meta/incomingWebhook",
            endpoint=self.refPortalImplementationFastApi.incomingWebhookFromMeta_GET,
            methods=["GET"]
        )

        # meta POST
        self.app.add_api_route(
            path=f"/meta/incomingWebhook",
            endpoint=self.refPortalImplementationFastApi.incomingWebhookFromMeta_POST,
            methods=["POST"]
        )

        # telegram
        self.app.add_api_route(
            path=f"/telegram/{self.incomingApiGuid}/incomingWebhook",
            endpoint=self.refPortalImplementationFastApi.incomingWebhookFromTelegram,
            methods=["POST"]
        )

        # manychattest
        self.app.add_api_route(
            path="/manychattest/approvegame/{refId}/{waId}/{gameId}",
            endpoint=self.refPortalImplementationFastApi.manyChatTest,
            methods=["POST"]
        )
        
        # Chat API routes for cross-device synchronization
        if chat_router:
            self.app.include_router(chat_router)
            self.logger.info("✅ Chat API router included successfully")
        else:
            self.logger.warning("⚠️ Chat API router not available")
        
        #statusCallBackLimit = self.limiter.exempt()(self.statusCallback)
        #self.app.add_url_rule(f'/twilio/{self.twilioApiGuid}/statusCallback', 'statusCallback', statusCallBackLimit, methods=['POST'])

#if __name__ == '__main__':
refPortalFastApi = RefPortalFastApi()
#refPortalApiAws.start()
app = refPortalFastApi.app
handler = Mangum(app=refPortalFastApi.app, lifespan="off")
    #asyncio.run(refPortalApi.sendMessageTemplate('43679'))
    #asyncio.run(refPortalApi.approveGame('43679', '26396ab6'))
"""
    flow 
        #1 send askToJoin_+972
        #2 IncomingWebhook - When message received the message
                Create user using MobileNo as LoginId
                Send template message to referee with JoiningConfirmation_+972...  (open 24hrs window)
        #3 IncomngWebhook - When message received send Registration message with link to registration page
        #4 When registration submitted - Create user and delete mobile user
"""
    