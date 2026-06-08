from http.client import OK
import platform
from fastapi import Request, Form, BackgroundTasks, Query, HTTPException, Header, WebSocket, WebSocketDisconnect
from starlette.requests import ClientDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import Response
from fastapi.responses import PlainTextResponse
from jinja2 import Template
from functools import wraps
import requests
import asyncio
import json
import io
import socket
import os
import re
import uuid
import time
import base64
from urllib.parse import quote, unquote
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime, timedelta, timezone as _tz
from decimal import Decimal
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger
from shared.handleUsers import HandleUsers
from shared.handleTournaments import HandleTournaments
from shared.handleRefereeData import HandleRefereeData
from shared.messaging import MessagingService
from shared.dockerClient import DockerClient
from shared.orgRelated import OrgServiceBase
from shared.refereeProcessServiceClient import invokeLambdaFunction
from shared.refereeProcessService import RefereeProcessService
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.configManager import ConfigManager
from shared.mediaFileCollector import MediaFileCollector
from shared.reportsService import ReportsService
from rpApi.websocketManager import WebSocketManager
try:
    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    PDF_MERGE_AVAILABLE = True
except ImportError:
    PDF_MERGE_AVAILABLE = False
from shared.db import CacheService
from shared.orgRelated import OrgServiceFactory
from shared.urlParser import URLParser
from rpApi.pollService import PollService
from shared.commute_service import CommuteService

# Sent from handlers when list/interactive UI was already sent; truthy so fallbacks in incomingWebhook do not run.
# Stripped to None on the reply dict so messaging clients never send this string to the user.
INCOMING_WEBHOOK_REPLY_INTERACTIVE_ONLY = '__refportal_incoming_webhook_interactive_only__'

class RefPortalImplementationApi():
    # The __init__ method now accepts all dependencies instead of creating them.
    def __init__(self, 
                 logger: Logger, 
                 cacheService: CacheService,
                 messagingService: MessagingService,
                 handleUsers: HandleUsers,
                 handleTournaments: HandleTournaments,
                 handleRefereeData: HandleRefereeData,
                 dockerClient: DockerClient,
                 refereeProcessService: RefereeProcessService=None,
                 commuteService: CommuteService=None,
                 orgServiceFactory: OrgServiceFactory=None,
                 pollService: PollService=None,
                 awsSqsClient=None,
                 awsS3Client=None,
                 referees_data: tuple=None,
                 config: dict=None,
                 llm_response_cache=None  # Optional LLM response cache instance
                 ):
        
        # Store injected dependencies
        self.logger = logger
        self.cacheService = cacheService
        self.messagingService = messagingService
        self.handleUsers = handleUsers
        self.handleTournaments = handleTournaments
        self.handleRefereeData = handleRefereeData
        self.dockerClient = dockerClient
        self.refereeProcessService = refereeProcessService
        self.commuteService = commuteService
        self.orgServiceFactory = orgServiceFactory
        self.pollService = pollService
        self.awsSqsClient = awsSqsClient
        self.awsS3Client = awsS3Client
        self.config = config or {}
        self.llmConfig = self.config.get('LLM', {})
        self.llm_response_cache = llm_response_cache  # Store injected cache
        
        self.logger.sendMessage = self.messagingService.greenApiSendMessage

        # Log cache status
        if self.llm_response_cache:
            self.logger.info(f"LLM response cache injected: {type(self.llm_response_cache).__name__}")
        else:
            self.logger.info("No LLM response cache provided")

        self.urlParser = URLParser()

        self.tenants = self.cacheService.getTenants(forceReload=True)
        self.activeTenantKeys = [ tenantKey for tenantKey, tenant in self.tenants.items() if tenant.get('active') == True ]
        
        # Unpack referees data
        if referees_data:
            (self.globalRefereesByMobile, self.refereesByRefId, self.refereesByMobile, self.refereesByGuid, self.globalRefereesByName) = referees_data
        else:
            self.globalRefereesByMobile, self.refereesByRefId, self.refereesByMobile, self.refereesByGuid, self.globalRefereesByName = {}, {}, {}, {}, {}

        #self.updateStatus(self.refereesByMobile['IL#football#2025-26'])

        # Store injected configuration
        self.env = self.config.get('env')
        self.adminMobile = self.config.get('adminMobile')
        self.botMobileNumbers = self.config.get('botMobileNumbers')
        self.rootServiceUrlBase = self.config.get('rootServiceUrlBase')
        self.docsServiceUrlBase = self.config.get('docsServiceUrlBase')
        self.domainUrlBase = self.config.get('domainUrlBase')
        self.apiServiceUrlBase = self.config.get('apiServiceUrlBase')

        # AWS configuration
        self.awsRegion = self.config.get('aws', {}).get('region')
        self.twilioQueueUrl = self.config.get('twilioQueueUrl')
        self.twilioQueueMaxNumberOfMessages = int(self.config.get('twilioQueueMaxNumberOfMessages', 1))
        self.twilioQueueWaitTimeSeconds = int(self.config.get('twilioQueueWaitTimeSeconds', 20))

        self.websocketManager = WebSocketManager(logger=self.logger)
        
        # Initialize media file collector
        self.mediaFileCollector = MediaFileCollector(logger=self.logger)
        
        # Track pending media files for multi-page document grouping
        # Structure: {mobileNo: {'mediaFiles': [...], 'timestamp': datetime, 'messageSid': '...', 'timeout_task': Task}}
        self.pending_media_groups: dict[str, dict] = {}
        self.media_grouping_window_seconds = 7  # Group media files sent within 15 seconds
        
        # Initialize email and PDF services
        self.reportsService = ReportsService(logger=self.logger)

        self.templates = Jinja2Templates(directory="../rpApi/templates")
        self.trackingDataStoragePath = os.getenv("TRACKING_DATA_STORAGE_PATH", "/run/data/tracking_data")
        self.generateFieldsDetails()
        self.getConfigFiles()
        self.getIntents()
        self.watchFiles()
        self.handleRefereeData.loadActiveRefereeDetails()

        self.cacheService._redis_set(key='guy:shachar:test', data={'name': 'guy shachar'}, ttl_seconds=3600)
        test = self.cacheService._redis_get(key='guy:shachar:test')
        self.logger.info(f"Test data: {test}")
        openText=f'Ref Portal Api Shared {helpers.localNow().strftime("%Y-%m-%d %H:%M:%S")} build#{self.config.get("buildDate")} host={socket.gethostname()}'
        self.logger.info(openText)

    @property
    def llm_enhancer(self):
        """
        Lazy-loading property for LLM enhancer.
        Only creates the instance when first accessed.
        """
        if not hasattr(self, '_llm_enhancer'):
            # Check if LLM is enabled in config
            if not self.llmConfig.get('enabled', False):
                self._llm_enhancer = None
                return None
            
            try:
                from rpApi.webhook_llm_integration import (
                    create_llm_webhook_handler,
                    create_llm_webhook_integration,
                    create_webhook_llm_enhancer,
                )
                from shared.bedrockClient import BedrockClient

                bedrock_client = BedrockClient(
                    logger=self.logger,
                    awsRegion=self.config.get('aws', {}).get('bedrock_region'),
                    bedrockModelId=self.llmConfig.get('bedrockModelId'),
                    bedrockModelArn=self.llmConfig.get('bedrockModelArn'),
                    bedrockKbId=self.llmConfig.get('bedrockKbId'),
                    truncate_model_token_limits=self.llmConfig.get('bedrockTruncateModelTokenLimits'),
                )

                llm_integration = create_llm_webhook_integration(
                    logger=self.logger,
                    bedrock_client=bedrock_client,
                    cacheService=self.cacheService,
                    config=self.config,
                    handle_referee_data=self.handleRefereeData,
                )
                if not llm_integration:
                    self.logger.error("LLMWebhookIntegration creation failed — llm_enhancer disabled")
                    self._llm_enhancer = None
                else:
                    webhook_handler = create_llm_webhook_handler(llm_integration)
                    self._llm_enhancer = create_webhook_llm_enhancer(
                        logger=self.logger,
                        cacheService=self.cacheService,
                        llm_integration=llm_integration,
                        webhook_handler=webhook_handler,
                        config=self.config,
                        response_cache=self.llm_response_cache,
                    )
            except Exception as e:
                self.logger.error(f"Failed to create LLM enhancer:", e)
                self._llm_enhancer = None
        
        return self._llm_enhancer

    @property
    def schedule_agent(self):
        if not hasattr(self, "_schedule_agent"):
            if not ConfigManager.get_config_bool(self.config, "scheduleAgentEnabled", True):
                self._schedule_agent = None
                self.logger.info("ScheduleAgent disabled (scheduleAgentEnabled in config)")
            else:
                try:
                    from rpApi.agents.schedule_agent import ScheduleAgent
                    from shared.bedrockClient import BedrockClient
                    bedrock_client = BedrockClient(
                        logger=self.logger,
                        awsRegion=self.config.get("aws", {}).get("bedrock_region"),
                        bedrockModelId=self.llmConfig.get("bedrockModelId"),
                        bedrockModelArn=self.llmConfig.get("bedrockModelArn"),
                        bedrockKbId=self.llmConfig.get("bedrockKbId"),
                        truncate_model_token_limits=self.llmConfig.get("bedrockTruncateModelTokenLimits"),
                    )
                    self._schedule_agent = ScheduleAgent(
                        logger=self.logger,
                        cacheService=self.cacheService,
                        bedrockClient=bedrock_client,
                        handleRefereeData=self.handleRefereeData,
                        commuteService=self.commuteService,
                        llmConfig=self.llmConfig,
                    )
                    self.logger.info("ScheduleAgent initialized")
                except Exception as e:
                    self.logger.error("Failed to initialize ScheduleAgent:", e)
                    self._schedule_agent = None
        return self._schedule_agent

    def getConfigFiles(self):
        self.intents_ = {}
        url = f'{self.docsServiceUrlBase}config/intentPhrases.json'
        response = requests.get(url)
        status_code = response.status_code
        if status_code != 200:
            self.logger.error(f'Error in getConfigFiles: {status_code}')
            self.intents_["intentPhrases"] = {}
            return
        self.intents_["intentPhrases"] = response.json()
        url = f'{self.docsServiceUrlBase}config/information.txt'
        response = requests.get(url)
        self.intents_["newJoiner"] = response.text
        pass

    def getIntents(self):
        url = f'{self.docsServiceUrlBase}config/intentPhrases2.json'
        response = requests.get(url)
        status_code = response.status_code
        if status_code != 200:
            self.logger.error(f'Error in getIntents: {status_code}')
            self.intent_phrases = {}
            return

        self.intent_phrases = response.json()

        for value in self.intent_phrases.values():
            if value.get('type') == 'file' and value.get('file').endswith('.txt'):
                url = f'{self.docsServiceUrlBase}{value.get("file")}'
                response = requests.get(url)
                value["content"] = response.text
            elif value.get('type') == 'url' and value.get('url').startswith('http'):
                url = value['url']
                value["content"] = url
            elif value.get('type') == 'function':
                function = getattr(self, value.get('function'))
                value["content"] = function()

    def getFieldsDetails(self):
        return self.fieldsDetails

    def generateFieldsDetails(self):
        self.fieldsDetails = {}
        for tenantKey in self.cacheService.getTenants().keys():
            self.fieldsDetails[tenantKey] = {
                key: {"field": field, "variants": list(field.values()), "findText": key + ' '.join(helpers.flatten_values(field)), "details": self.generateFieldDetails(field)}
                for key, field in self.cacheService.getFields(tenantKey=tenantKey).items()
            }
        pass

    def generateFieldDetails(self, field):
        fieldDetails = f'*פרטי המגרש:*'
        fieldDetails += f' {field.get('title')}'
        fieldAddressDetails = field.get('addressDetails') 
        fieldLocation = None
        #'latitude': to_coordinates_lat, 'longitude': to_coordinates_lng, 'name': field['title'], 'address': fieldAddressDetails['address']})
        if fieldAddressDetails:
            fieldDetails += f'\nכתובת: {fieldAddressDetails.get('address')}'
            to_coordinates_lat = fieldAddressDetails.get('coordinates', {}).get('lat')
            to_coordinates_lng = fieldAddressDetails.get('coordinates', {}).get('lng')
            fieldLocation = {
                "latitude": to_coordinates_lat,
                "longitude": to_coordinates_lng,
                "name": field.get('title'),
                "address": fieldAddressDetails.get('address')
            }
            #fieldDetails += f'\nhttps://www.google.com/maps?q={to_coordinates_lat},{to_coordinates_lng}'
            if field.get('level'):
                fieldDetails += f'\nרמת מתקן: {field['level']}'
            if field.get('contact'):
                fieldDetails += f'\nאחראי: {field['contact']}'
            if field.get('phone'):
                fieldDetails += f'\nטלפון: {field['phone']}'
            if fieldAddressDetails.get('wazeLink'):
                fieldDetails += f'\n{fieldAddressDetails["wazeLink"]}'
        
        return { "reply": fieldDetails, "location": fieldLocation }

    def watchFiles(self):
        try:
            pass
        except Exception as ex:
            self.logger.error(f'watchFiles error', ex)

    async def dispatch(self, request: Request, call_next):
        print(f"[LOG] {request.method} {request.url}")
        self.beforeRequestFunc()
        response = await call_next(request)
        return response
    
    def beforeRequestFunc(self, request:Request):
        try:
            self.logger.debug(f"Intercepted request to: {request.path_params} from: {self.ip}")
        except Exception as ex:
            self.logger.error(f'beforeRequestFunc {request.path_params}', ex)    

    def manyChatTest(self, request:Request, refId, waId, gameId):
        pass

    def downloadGameIcsFile(self, request:Request, fileId):
        if len(fileId.split('_')) == 2:
            gameId = fileId.split('_')[1]
        else:
            gameId = fileId
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        if not gameDetail:
            self.logger.warning(f"downloadGameIcsFile: game not found gameId={gameId}")
            return JSONResponse(status_code=404, content={"error": "Game not found"})
        calendar = self.handleTournaments.createCalendar(games=[gameDetail])
        if calendar is None:
            self.logger.error(f"downloadGameIcsFile: createCalendar failed gameId={gameId}")
            return JSONResponse(status_code=500, content={"error": "Could not build calendar"})
        return StreamingResponse(content=calendar, media_type='text/calendar')

    def downloadIcsFile1(self, request:Request, fileId):
        self.logger.info(f"downloadIcsFile: fileId={fileId}")

        boto3s3 = self.awsS3Client
        bucketName = helpers.getBucketName()

        if len(fileId.split('_')) == 2:
            gameId = fileId.split('_')[1]
        else:
            gameId = fileId
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        if not gameDetail:
            self.logger.warning(f"downloadIcsFile1: game not found gameId={gameId}")
            return JSONResponse(status_code=404, content={"error": "Game not found"})
        tenantKey = self.cacheService.dbClient.getTenantKey(season=gameDetail.get('season'))
        (fileId, icsGameFilename) = helpers.getGameIcsFilename(tenantKey=tenantKey, gameId=gameId)
        s3Key = icsGameFilename.lstrip(os.getenv("MY_DATA_FOLDER", "/run/data/"))
        try:
            boto3s3.download_file(bucketName, s3Key, icsGameFilename)
        except Exception as ex:
            self.logger.error(f"downloadIcsFile error", ex)
        icsFileExists = os.path.exists(icsGameFilename)
        if not icsFileExists:
            (fileId, icsGameFilename) = helpers.getGameIcsFilename(tenantKey=tenantKey, gameId=fileId)
            s3Key = icsGameFilename.lstrip(os.getenv("MY_DATA_FOLDER", "/run/data/"))
            try:
                boto3s3.download_file(bucketName, s3Key, icsGameFilename)
            except Exception as ex:
                self.logger.error(f"downloadIcsFile error", ex)
            icsFileExists = os.path.exists(icsGameFilename)
            if not icsFileExists:
                (fileId, icsGameFilename) = helpers.getGameIcsFilename(tenantKey=tenantKey, gameId=f'_{fileId}')
                s3Key = icsGameFilename.lstrip(os.getenv("MY_DATA_FOLDER", "/run/data/"))
                try:
                    boto3s3.download_file(bucketName, s3Key, icsGameFilename)
                except Exception as ex:
                    self.logger.error(f"downloadIcsFile error", ex)
                icsFileExists = os.path.exists(icsGameFilename)
                if not icsFileExists:
                    return JSONResponse(content="הקישור לא תקין", status_code=404)

        return FileResponse(path=icsGameFilename, media_type='text/calendar')
    
    async def root(self, request:Request):
        return RedirectResponse(url='welcome')  # Redirects to the 'home' route

    async def welcome(self, request:Request):
        return RedirectResponse(f'{self.domainUrlBase}welcome.html')

    async def getHealth(self, request: Request):
        return await self.health()

    async def health(self):
        logs = await self.getServiceLogs()
        logsJson = jsonHelper.save_to_json(logs)
        self.logger.info('health')
        return f'Health is ok {helpers.localNow()}...\n{logsJson}'

    async def delay(self, request:Request):
        await asyncio.sleep(10)
        return 'delay...'
    
    async def getReferee(self, request:Request):
        return RedirectResponse(f'{self.domainUrlBase}index.html')

    async def getRefereeSubmit(self, request:Request):       
        mobileNo = (await request.form()).get('mobileNo').strip()
        
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")
        
        result = self.globalRefereesByMobile[mobileNo]
        if 'password' in result:
            del result['password']

        if result:
            return f"{result}\n{helpers.localNow()}"
        else:
            return f"{helpers.localNow()} {mobileNo} לא נמצא, אנא פנה למנהל המערכת"

    async def askToJoin(self, mobileNo):
        self.logger.info(f"mobileNo: {mobileNo}")

        mobileNo = MessagingService.adjustMobileNo(mobileNo=mobileNo)
        checkWhatsapp = await self.messagingService.checkWhatsapp(mobileNo)

        error = None
        if not checkWhatsapp:
            error = f'מספר הנייד {mobileNo} לא תקין'

        if error == None:
            msgSid = await self.messagingService.sendOnBoardingJoinConfirmation(to=mobileNo)
            return f"{helpers.localNow()} שופט {mobileNo} נשלחה בקשת הצטרפות"
        else:
            return f"{helpers.localNow()} שופט {mobileNo} נכשל בשליחת בקשת הצטרפות {error}, אנא פנה למנהל המערכת"

    async def processMobileNosPost(self, request:Request):
        mobileNos:list = await request.json()
        result = await self.processMobileNos(mobileNos=mobileNos)
        return 'Completed'
    
    async def processMobileNos(self, mobileNos):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNos: {mobileNos}")

        processed = await invokeLambdaFunction(logger=self.logger, cacheService=self.cacheService, refereeIds=mobileNos)
        
        if not processed:
            await self.refereeProcessService.startProcessByMobileNos(mobileNos=mobileNos)
        
        return f"{helpers.localNow()} בוצע"

    async def processMobileNo(self, request:Request, mobileNo):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")

        await self.processMobileNos( [ mobileNo ])
        return f"{helpers.localNow()} בוצע"

    async def addPending(self, request:Request):
        return self.templates.TemplateResponse("addPending.html", {
        "request": request})

    async def joinConfirmationReply(self, mobileNo, answer):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")

        checkWhatsapp = await self.messagingService.checkWhatsapp(mobileNo)

        error = None
        if not checkWhatsapp:
            error = f'מספר הנייד {mobileNo} לא תקין'
        elif answer == 'yes':
            self.cacheService.setRefereeProperty(mobileNo=mobileNo, value=True, propertyName='joinConfirmationReply')
            error = await self.handleUsers.addPendingReferee(mobileNo)
        else:
            self.cacheService.setRefereeProperty(mobileNo=mobileNo, value=False, propertyName='joinConfirmationReply')
            error = f'מספר הנייד {mobileNo} לא מעוניין להצטרף לשירות'

        if not error:
            msgSid = await self.messagingService.sendOnBoardingRegistration(to=mobileNo)
            return f"{helpers.localNow()} שופט {mobileNo} התווסף כמועמד למערכת"
        else:
            return f"{helpers.localNow()} {error}"

    async def addPendingSubmit(self, mobileNo):
        return self.addPending(mobileNo)
    
    async def registration(self, request:Request):
        return RedirectResponse(f'{self.domainUrlBase}registration.html')

    async def registrationSubmit(self, request:Request):
        mobileNo = MessagingService.adjustMobileNo(mobileNo=(await request.form()).get('mobileNo').strip())
        checkWhatsapp = await self.messagingService.checkWhatsapp(mobileNo)
        result = None
        if not checkWhatsapp:
            result = f'מספר הנייד {mobileNo} לא תקין (צריך להתחיל ב +972)'
            return PlainTextResponse(content=result, status_code=405)
    
        refId = (await request.form()).get('refId').strip()

        refName = (await request.form()).get('refName').strip()
        id = (await request.form()).get('id').strip()
        refPassword = (await request.form()).get('refPassword').strip()        
        refArea = (await request.form()).get('refArea').strip()        
        originAddress = (await request.form()).get('originAddress').strip()
        reminderInHours = int((await request.form()).get('reminderInHours').strip())
        timeArrivalInMins = int((await request.form()).get('timeArrivalInMins').strip())
        messageAcceptanceLimitation = eval((await request.form()).get('messageAcceptanceLimitation', 'True'))
        createGroups = eval((await request.form()).get('createGroups', 'True'))
        alwaysCreateChatGroup = eval((await request.form()).get('alwaysCreateChatGroup', 'False'))
        ignoreGroup4Singles = eval((await request.form()).get('ignoreGroup4Singles', 'False'))
        self.logger.info(f"registrationSubmit refId: {refId}, refName: {refName}, id: {id}, mobile: {mobileNo}")
        result = await self.handleUsers.updateReferee(mobileNo, refId, refName, id, refPassword, refArea, None, originAddress, \
            reminderInHours, timeArrivalInMins, self.handleUsers.getRandomColor(), str(uuid.uuid4()), messageAcceptanceLimitation, createGroups, alwaysCreateChatGroup, ignoreGroup4Singles)
        self.logger.debug(f"registrationSubmit result={result}")
                         
        if not result:
            self.reloadReferees()
            refereeDetail = self.handleUsers.getRefereeDetailByRefId(refId)
            mobileNo = refereeDetail['mobileNo']            
            msgSid = await self.messagingService.sendOnBoardingActivate(refereeDetail)
            message = f"קוד שופט {refId} {refName} נרשם למערכת"
            msgSid = await self.messagingService.sendMessage(to=self.adminMobile, message=message, skipOpenWindowCheck=True)
            return PlainTextResponse(content='הפרטים עודכנו בהצלחה')
        
        return PlainTextResponse(content=result)

    async def changePassword(self, request:Request):
        static_file_path = f"/static/changePassword.html?_t={helpers.localNow():%ssssss}"  # Relative to your project root
        return RedirectResponse(url=static_file_path)

    async def changePasswordSubmit(self, request:Request):
        form = await request.form()
        tenantKey = form.get('tenantKey').strip()
        refId = form.get('refId').strip()
        refPassword = form.get('refPassword').strip()
        result = await self.changePasswordByRefId(tenantKey=tenantKey, refId=refId, refPassword=refPassword)
        return PlainTextResponse(content=result)
    
    async def changePasswordByRefId(self, tenantKey, refId, refPassword):       
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"refId: {refId}")

        result = self.handleUsers.changeRefereePassword(tenantKey=tenantKey, refId=refId, refPassword=refPassword)
        
        text = None
        if result == True:
            await self.handleUsers.activate(refId)
            self.reloadReferees()
            text = f"קוד שופט {refId} סיסמא עודכנה בהצלחה"
        else:
            text = f"קוד שופט {refId} נכשל בשינוי סיסמא, אנא פנה למנהל המערכת"
        
        msgSid = await self.messagingService.sendMessage(to=self.adminMobile, message=text)
        return text

    async def activate(self, request:Request):
        return self.templates.TemplateResponse('activate.html')

    async def activateByMobileNo(self, mobileNo):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"activateByMobileNo: {mobileNo}")
        
        globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
        if not globalRefereeDetail or not globalRefereeDetail.get('name'):
            return f"{helpers.localNow()} {mobileNo} נכשל בהפעלת שופט, אנא פנה למנהל המערכת"
        
        for tenantKey in globalRefereeDetail['activeTenantKeys']:
            refereeDetail = await self.handleUsers.activate(tenantKey=tenantKey, mobileNo=mobileNo)

        await self.sendNewJoiner(mobileNo=mobileNo, tenantKeys=globalRefereeDetail['activeTenantKeys'])
        await self.messagingService.sendBotContact(to=mobileNo)
        #helpers.run_async_in_thread(self.processMobileNos, mobileNos=[ mobileNo ])
        return f"{helpers.localNow()} {mobileNo} שופט הופעל בהצלחה"

    async def deactivateByRefId(self, mobileNo):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")
        
        refereeDetail = await self.handleUsers.deactivate(mobileNo)

        if refereeDetail:
            return f"{helpers.localNow()} קוד שופט {mobileNo} שופט הושבת בהצלחה"
        else:
            return f"{helpers.localNow()} קוד שופט {mobileNo} נכשל בהשבתת שופט, אנא פנה למנהל המערכת"

    async def activateSubmit(self, request:Request):       
        mobileNo = (await request.form()).get('mobileNo').strip()
        # Handle the submitted parameters (e.g., print or save them)
        result = await self.activateByMobileNo(mobileNo=mobileNo)
        return PlainTextResponse(content=result)

    async def deactivate(self, request:Request):
        return self.templates.TemplateResponse('deactivate.html')

    async def deactivateSubmit(self, request:Request):       
        mobileNo = (await request.form()).get('mobileNo').strip()
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")
        
        refereeDetail = await self.handleUsers.deactivate(mobileNo=mobileNo)

        if refereeDetail:
            return PlainTextResponse(content=f"{helpers.localNow()} {mobileNo} שופט בוטל בהצלחה")
        else:
            return PlainTextResponse(content=f"{helpers.localNow()} {mobileNo} נכשל בביטול שופט, אנא פנה למנהל המערכת")

    async def sendNewJoiner(self, mobileNo:str, tenantKeys:list=[]):
        refereeDetail = self.globalRefereesByMobile[mobileNo]
        title = f'{refereeDetail["name"]}, ברוך הבא למערכת RefereeX'
        #message = self.intent_phrases["infromation.txt"]
        #message = await self.messagingService.getMessageTemplate(mobile=refereeDetail['mobileNo'], messageTemplate='newJoiner.txt')
        #message = f'{title},\n{message}'
        if self.messagingService.useMeta:
            message = f'{title},\nמצורף קובץ שמסביר את מגוון השירותים שהמערכת מציעה.'
            for tenantKey in tenantKeys:
                tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
                if tenant.get('whatsAppGroupLink'):
                    message += f'\nעל מנת להצטרף לקבוצת ה WhatsApp של {tenant.get('name')} יש ללחוץ על הקישור הבא:{tenant.get('whatsAppGroupLink')}'
            fileUrl = f'{self.docsServiceUrlBase}{quote("שירות RefereeX.pdf")}'
            self.messagingService.metaClient.sendDocumentMessage(to=mobileNo, message=message, filePath=fileUrl, filename='שירות RefereeX.pdf')
        else:
            await self.messagingService.sendMessage(to=mobileNo, message=title, performOpenWindowCheck=True)
        return f'מלל נשלח לשופט {mobileNo}'

    async def forceSend(self, mobileNo):
        self.logger.info(f"mobileNo: {mobileNo}")
        
        refereeDetail = await self.handleUsers.forceSend(mobileNo=mobileNo)

        if refereeDetail:
            return f"{helpers.localNow()} קוד שופט {mobileNo} שופט הופעל בהצלחה"
        else:
            return f"{helpers.localNow()} קוד שופט {mobileNo} נכשל בהפעלת שופט, אנא פנה למנהל המערכת"

    async def resetReminders(self, mobileNo, hours):
        now = helpers.localNow()
        timestamp = int(time.time())
        games = await self.getRefereeGames(mobileNo=mobileNo)
        for game in games:
            refGameNotifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], to=mobileNo)
            for notificationType, notification in refGameNotifications.items():
                if notification.get('status', 'created') == 'created' or not notification.get('sentDate'):
                    continue
                if (now - notification['sentDate']).total_seconds() < hours * 3600:
                    notification['status'] = 'created'
                    notification['sentDate'] = None
                    self.cacheService.setNotification(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType=notificationType, to=mobileNo, timestamp=timestamp, value=notification)

        return f"{helpers.localNow()} הגדרת התראות לשופט {mobileNo} אופסו בהצלחה"

    async def forceSendByMobileNo(self, mobileNo, objType, msgSid = None):
        self.logger.info(f"mobileNo: {mobileNo}")

        if not msgSid:
            msgSid = str(uuid.uuid4())[:16]

        globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
        activeTenantKeys = globalRefereeDetail['activeTenantKeys']
        for tenantKey in activeTenantKeys:
            refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
            if refereeDetail:
                obj = {'refId': refereeDetail['refId'], 'action': 'forceSend', 'objType': objType, 'status': 'created'}
                self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid, value=obj)
                return f"{helpers.localNow()} הבקשה לשליחה מחודשת התקבלה בהצלחה"

        return f"{helpers.localNow()} נכשלה השליחה לשופט {mobileNo}, אנא פנה למנהל המערכת"

    async def forceSendSubmit(self, request:Request):       
        mobileNo = (await request.form()).get('mobileNo').strip()
        return self.forceSendByMobileNo(mobileNo=mobileNo, objType='games')

    async def refreshLeaguesTables(self, request:Request):
        return self.templates.TemplateResponse('refreshLeaguesTables.html')

    async def refreshLeaguesTablesSubmit(self, request:Request): 
        tenantKey = (await request.form()).get('tenantKey').strip()
        leagueName = (await request.form()).get('leagueName').strip()
        result = await self.refreshLeaguesTablesByTenant(tenantKey=tenantKey, tournamentName=leagueName)
        return result

    async def refreshLeaguesTables(self, leagueName=None):       
        for tenantKey in self.activeTenantKeys:
            await self.refreshLeaguesTablesByTenant(tenantKey=tenantKey, tournamentName=leagueName)

        return f"{helpers.localNow()} טבלאות יעודכנו בהמשך"

    async def refreshLeaguesTablesByTenant(self, tenantKey, tournamentName=None):       
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"tenantKey: {tenantKey} leagueName: {tournamentName}")
        
        orgService = self.orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)
        helpers.run_async_in_thread(orgService.refreshLeaguesTables, tenantKey=tenantKey, tournamentName=tournamentName)

        return f"{helpers.localNow()} טבלאות בשם {tournamentName} {tenantKey} יעודכנו בהמשך"

    async def cancelGameApproval(self, mobileNo):
        self.logger.info(f'cancelGameApproval mobileNo: {mobileNo}')

        result = None
        noOfCancellations = 0
        noOfCompleted = 0
        localNow = helpers.localNow()
        globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
        for tenantKey in globalRefereeDetail.get('activeTenantKeys', []):
            recentTemplates = helpers.sortDictByProperty(self.cacheService.getRefereeTemplates(tenantKey=tenantKey, fromMobile=mobileNo, status='created'), 'created', True)
            for msgSid, template in recentTemplates.items(): 
                if template['action'] == 'approveGame' and localNow - template['created'] < timedelta(seconds=5*60):
                    if template['status'] == 'created':
                        template['status'] = 'cancelled'
                        noOfCancellations += 1
                        self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid, value=template)
                    elif template['status'] == 'completed':
                        noOfCompleted += 1
    
        result = ''
        if noOfCancellations > 0:
            result += f"{helpers.localNow()} {noOfCancellations} בקשות לאישור המשחק בוטלו בהצלחה"
        if noOfCompleted > 0:
            if result:
                result += '\n'
            result += f"{helpers.localNow()} {noOfCompleted} בקשות לאישור המשחק אושרו בהצלחה"
        if noOfCancellations == 0 and noOfCompleted == 0:
            result = f"{helpers.localNow()} לא נמצאו בקשות לאישור"
        
        return result

    async def getGameUpdateTemplate(self, mobileNo, gameId):
        self.logger.info(f'getGameUpdateTemplate mobileNo: {mobileNo}, gameId: {gameId}')
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        refereeDetail = self.cacheService.getReferees(tenantKey=gameDetail['tenantKey'], mobileNo=mobileNo)
        orgService = self.orgServiceFactory.get_org_service_by_tenant(tenantKey=gameDetail['tenantKey'])
        url = await orgService.getPostGameUpdateTemplate(refId=refereeDetail['refId'], gameId=gameId)
        
        if url is None:
            return JSONResponse(content="הקישור לא תקין", status_code=404, media_type="text/plain")

        return RedirectResponse(url=url)

    def updateStatus(self, referees:dict):
        for id, referee in referees.items():
            if referee.get('status') and referee.get('status') != 'temp':
                continue
            referee['status'] = 'draft'
            self.cacheService.setRefereeProperty(tenantKey=referee['tenantKey'], mobileNo=referee['mobileNo'], value=referee)

    def reloadReferees(self):
        (self.globalRefereesByMobile, self.refereesByRefId, self.refereesByMobile, self.refereesByGuid, self.globalRefereesByName) = self.handleUsers.getAllReferees()
        return f"{helpers.localNow()} מאגר השופטים נטען מחדש"

    async def reloadIntents(self):
        self.getIntents()
        return f"{helpers.localNow()} קונפיגורציה נטענה מחדש"

    async def getServiceLogs(self, tail = 1):
        if self.dockerClient is None:
            return []
        dockerServices = await self.dockerClient.getServices('refportalservice')
        logs = []
        for service in dockerServices:
            self.logger.info(f'service={service.name}')
            serviceLogs = await self.dockerClient.getServiceLogs(service, tail)
            logs.append(serviceLogs)
        return logs

    def updateFieldAddress(self, tenantKey, fieldName, latitude, longitude):
        field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldName)
        if not field:
            return None
        
        addressDetails = field['addressDetails']
        addressDetails['coordinates']['lat'] = latitude
        addressDetails['coordinates']['lng'] = longitude
        addressDetails['wazeLink'] = f'https://www.waze.com/ul?ll={latitude},{longitude}&navigate=yes'
        self.cacheService.setField(tenantKey=tenantKey, fieldName=field['title'], value=field)
        return field
    
    async def checkWindow(self, mobileNo, message=None):
        totalChecked = 0
        totalOpened = 0
        if mobileNo:
            refereeDetail = self.globalRefereesByMobile[mobileNo]
            windowIsOpen = await self.handleRefereeData.handleWindowOpenReminder(refereeDetail=refereeDetail, message=message)
            if windowIsOpen:
                totalOpened+=1
            totalChecked+=1
        else:
            for mobileNo, refereeDetail in self.handleRefereeData.activeRefereesByMobile.items():
                windowIsOpen = await self.handleRefereeData.handleWindowOpenReminder(refereeDetail=refereeDetail, message=message)
                if windowIsOpen:
                    totalOpened+=1
                totalChecked+=1
    
        return totalChecked, totalOpened

    def setGameUpdateProp(self, gameSummary, data, propertyName, controlName, expression, errorMsg):
        value = gameSummary.get(propertyName)
        if expression(value):
            value = ''
            #raise Exception(errorMsg)
        if isinstance(value, str):
            value = value.strip()
        data[controlName] = value

    async def postGameUpdate(self, mobileNo, msgSid, summary):
        gameSummary = {}
        key = None
        value = None
        for line in summary.split('\n'):
            if line.strip().endswith(':'):
                if key:
                    gameSummary[key] = value
                    key = None
                    value = None
                key = line[:line.find(':')]
            elif not key and ':' in line:
                gameSummary[line.split(':')[0]] = line.split(':')[1].strip()
                key = None
            elif key and line and not value:
                value = line.strip()
        if key:
            gameSummary[key] = value

        gameId = gameSummary.get('מזהה')

        result = await self.updateGameReport(mobileNo=mobileNo, gameId=gameId, gameSummary=gameSummary, msgSid=msgSid)
        return result

    async def updateGameReport(self, mobileNo, gameId, gameSummary, msgSid=None):
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        if gameDetail is None:
            return 'המשחק לא קיים במערכת'

        tenantKey = gameDetail['tenantKey']
        tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
        gameUpdateTags = tenant.get('gameUpdateTags')
        refereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
        refId = refereeDetail.get('refId')
        if refereeDetail is None or refId not in gameDetail.get('mainReferees', []):
            return 'אתה לא השופט הראשי במשחק'
       
        self.logger.info(f'postGameUpdate mobileNo: {mobileNo} gameId: {gameId}')

        data = {}

        try:
            for tag, tagValue in gameUpdateTags.items():
                controlName = tagValue['field']
                self.setGameUpdateProp(gameSummary=gameSummary, data=data, propertyName=tag, controlName=controlName, expression=lambda x: x is None, errorMsg=f'{tag} לא תקין/ה')

            homeTeamScore = gameSummary.get('ביתית סיום')
            guestTeamScore = gameSummary.get('אורחת סיום')
            if homeTeamScore and guestTeamScore:
                gameDetail['homeTeamScore'] = homeTeamScore
                gameDetail['guestTeamScore'] = guestTeamScore
                self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], gamePk=gameDetail['gamePk'], value=gameDetail)

                template = { 'action': 'postGameUpdate', 'gameId': gameId, 'data': data, 'status': 'created' }
                self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid or str(uuid.uuid4())[:16], value=template)
        
                return f"{helpers.localNow()} הבקשה לעדכון פרטי המשחק התקבלה בהצלחה"

        except Exception as ex:
            return self.logger.error(f'postGameUpdate error', ex, refereeDetail=refereeDetail)
        
        return f"{helpers.localNow()} הבקשה לעדכון פרטי המשחק נכשלה"

    async def updateArea(self, tenantKey, mobileNo, area):
        self.logger.info(f'updateArea mobileNo={mobileNo} area={area}')
        if not area:
            return f"{helpers.localNow()} הבקשה לעדכון המחוז נכשלה"
        self.handleUsers.updateRefereeArea(tenantKey=tenantKey, mobileNo=mobileNo, area=area)
        return f"{helpers.localNow()} הבקשה לעדכון המחוז התקבלה בהצלחה"

    async def poll_sqs(self):
        while True:
            # Receive message from SQS queue
            response = self.awsSqsClient.receive_message(
                QueueUrl=self.twilioQueueUrl,
                MaxNumberOfMessages=self.twilioQueueMaxNumberOfMessages,
                WaitTimeSeconds=self.twilioQueueWaitTimeSeconds  # long polling
            )

            messages = response.get('Messages', [])
            if not messages:
                continue

            for message in messages:
                self.logger.debug(f"Twilio SQS Received:", message['Body'])

                # Process the message here...

                # Delete message from queue after processing
                self.awsSqsClient.delete_message(
                    QueueUrl=self.twilioQueueUrl,
                    ReceiptHandle=message['ReceiptHandle']
                )

            await asyncio.sleep(1)
    
    async def pollPreview(self, request: Request, pollId: str):
        try:
            # Get poll data
            if not self.pollService:
                return HTMLResponse(
                    content="<html><body><h1>Poll service not available</h1></body></html>",
                    status_code=503
                )
            
            urlSegments = request.url.path.split('/')[2:]
            text = '_'.join(urlSegments)

            poll_data = self.pollService.get_poll(pollId=pollId)
            
            if not poll_data:
                return HTMLResponse(
                    content="<html><body><h1>Poll not found</h1><p>The poll you're looking for doesn't exist or has expired.</p></body></html>",
                    status_code=404
                )
            
            # Extract poll information
            poll_title = poll_data.get('title', 'Poll')
            poll_description = poll_data.get('description', '')
            questions_count = len(poll_data.get('questions', []))
            
            # Build WhatsApp URL
            # Format: wa.me/PHONENUMBER?text=MESSAGE
            message = f"הצטרף לסקר: {poll_title}"
            if poll_description:
                message += f"\n{poll_description}"
            
            #text = f'pollVote_{pollId}'
            # Remove + and spaces from phone number for wa.me
            whatsapp_url = self.messagingService.getWhatsAppUrl(text=text)
            
            # Build preview URL (current page URL)
            preview_url = str(request.url)
            
            # Build logo URL for Open Graph preview
            # Use docsServiceUrlBase if available, otherwise domainUrlBase, fallback to request base URL
            logo_base_url = self.docsServiceUrlBase or self.domainUrlBase or str(request.base_url).rstrip('/')
            logo_url = f"{logo_base_url}/images/RefereeX.png"
            
            # Create HTML with Open Graph meta tags for rich previews
            html_content = f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Primary Meta Tags -->
    <title>{poll_title}</title>
    <meta name="title" content="{poll_title}">
    <meta name="description" content="{poll_description or 'הצטרף לסקר'}">
    
    <!-- Open Graph / Facebook / WhatsApp -->
    <meta property="og:type" content="website">
    <meta property="og:url" content="{preview_url}">
    <meta property="og:title" content="{poll_title}">
    <meta property="og:description" content="{poll_description or f'סקר עם {questions_count} שאלות'}">
    <meta property="og:image" content="{logo_url}">
    <meta property="og:image:width" content="640">
    <meta property="og:image:height" content="640">
    <meta property="og:image:alt" content="RefereeX Logo">
    
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
            box-sizing: border-box;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
        }}
        h1 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 28px;
        }}
        .description {{
            color: #666;
            margin-bottom: 30px;
            font-size: 16px;
            line-height: 1.6;
        }}
        .info {{
            background: #f5f5f5;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 30px;
            color: #555;
        }}
        .redirecting {{
            color: #999;
            font-size: 14px;
            margin-top: 20px;
        }}
        .spinner {{
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 30px;
            height: 30px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }}
        .logo {{
            max-width: 120px;
            height: auto;
            margin: 0 auto 20px;
            display: block;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <img src="{logo_url}" alt="RefereeX" class="logo">
        <h1>{poll_title}</h1>
        {f'<p class="description">{poll_description}</p>' if poll_description else ''}
        <div class="info">
            <strong>מספר שאלות:</strong> {questions_count}
        </div>
        <div class="spinner"></div>
        <p class="redirecting">מעבר לוואטסאפ...</p>
    </div>
    
    <script>
        // Redirect to WhatsApp immediately
        window.location.href = "{whatsapp_url}";
        
        // Fallback: if redirect doesn't work, show manual link after 2 seconds
        setTimeout(function() {{
            var fallbackDiv = document.createElement('div');
            fallbackDiv.innerHTML = '<a href="{whatsapp_url}" style="display: inline-block; margin-top: 20px; padding: 15px 30px; background: #25D366; color: white; text-decoration: none; border-radius: 10px; font-weight: bold;">לחץ כאן לפתיחת וואטסאפ</a>';
            document.querySelector('.container').appendChild(fallbackDiv);
        }}, 2000);
    </script>
</body>
</html>"""
            
            return HTMLResponse(content=html_content)
            
        except Exception as ex:
            self.logger.error(f"❌ Error in poll_preview for poll {pollId}: {ex}", ex)
            return HTMLResponse(
                content=f"<html><body><h1>Error</h1><p>An error occurred: {str(ex)}</p></body></html>",
                status_code=500
            )

    def findFieldDetails(self, fromDetails, fieldToSearch:str, customData:dict=None):
        try:
            if fieldToSearch:
                allFieldDetails:dict = {}
                for tenantKey, fields in self.fieldsDetails.items():
                    if tenantKey in fromDetails.get('activeTenantKeys'):
                        allFieldDetails = helpers.merge_nested_dicts(allFieldDetails, fields)
                bestMatchFieldTitle = helpers.find_intuitive_matches(fieldToSearch.strip(), allFieldDetails)
                if bestMatchFieldTitle:
                    fieldDetails = allFieldDetails.get(bestMatchFieldTitle[0])
                    if fieldDetails:
                        if customData and customData.get('actionType') == 'answer_fieldTextSearch':
                            promptButtons = []
                            promptButtons.append(
                            {
                                "sub_type": "quick_reply",
                                "id": "yes",
                                "text": "כן"
                            })
                            promptButtons.append(
                            {
                                "sub_type": "quick_reply",
                                "id": "no",
                                "text": "לא"
                            })

                            return self.fieldUpdateReply(mobileNo=fromDetails.get('mobileNo'), originalMsgSid=customData.get('originalMsgSid'), field=fieldDetails.get('field'), promptButtons=promptButtons, latitude=customData.get('latitude'), longitude=customData.get('longitude'), retry=customData.get('retry'))
                        
                        return fieldDetails
        except Exception as ex:
            self.logger.error(f'findFieldDetails', ex)
        return None

    def pwaGetTenants(self, request:Request):
        tenants = self.cacheService.getTenants()
        convertedValue = jsonHelper.preJsonSetToDynamoDb(tenants)
        content= {
            "data": convertedValue,
            "success": True
        }
        return JSONResponse(
            content=content, 
            status_code=200,
            headers={"Content-Type": "application/json"}
        )

    def pwaGetRoles(self, request:Request):
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            roles = {}
            # Check if there's a stored push subscription
            if mobileNo:
                for _tenantKey in self.activeTenantKeys:
                    roles[_tenantKey] = self.cacheService.getRoles(tenantKey=_tenantKey)

            convertedValue = jsonHelper.preJsonSetToDynamoDb(roles)
            content = {
                "data": convertedValue,
                "success": True
            }
            return JSONResponse(
                content=content,
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        except Exception as ex:
            self.logger.error(f'Error in pwaGetRoles: {ex}', exc_info=True)
            return JSONResponse(
                content={"data": [], "success": False, "error": str(ex)},
                status_code=500,
                headers={"Content-Type": "application/json"}
            )

    def pwaGetReferees(self, request:Request):
        try:
            mobileNo = request.state.mobile_no
            if mobileNo != self.adminMobile:
                return JSONResponse(
                    content={"data": [], "success": False, "error": "Unauthorized"},
                    status_code=401,
                    headers={"Content-Type": "application/json"}
                )

            # Get referees from globalRefereesByMobile
            _tenantKey = unquote(request.query_params.get('tenantKey', ''))
            if _tenantKey:
                tenantKeys = [_tenantKey]
            else:
                tenantKeys = list(self.activeTenantKeys)
            
            referees = {}
            for tenantKey in tenantKeys:
                for mobileNo, refereeDetail in self.refereesByMobile.get(tenantKey, {}).items():
                    # Create a safe copy without sensitive data
                    if mobileNo in referees:
                        continue
                    referees[mobileNo] = {
                        'mobileNo': mobileNo,
                        'name': refereeDetail.get("name", ""),
                        'activeTenantKeys': refereeDetail.get('activeTenantKeys', []),
                        'passwordExists': 'password' in refereeDetail #and refereeDetail['password'].strip() != ''
                    }
                
            # Sort by name for better UX
            refereesList = referees.values()
            refereesList = sorted(refereesList, key=lambda x: x.get('name', '') + '@@@' + x.get('refId', ''))

            content = {
                "data": refereesList,
                "success": True
            }
            return JSONResponse(
                content=content,
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
        except Exception as ex:
            self.logger.error(f'Error in getReferees: {ex}', exc_info=True)
            return JSONResponse(
                content={"data": [], "success": False, "error": str(ex)},
                status_code=500,
                headers={"Content-Type": "application/json"}
            )

    def pwaGetRefereeTemplates(self, request: Request):
        """Admin-only: get referee templates with filters (action, status, fromDate, toDate)."""
        try:
            mobileNo = request.state.mobile_no#self.getEffectedMobileNo(request=request)
            _tenantKey = unquote(request.query_params.get('tenantKey', ''))
            _action = request.query_params.get('action', '')
            _status = request.query_params.get('status', '')
            _fromDate = request.query_params.get('fromDate', '')
            _toDate = request.query_params.get('toDate', '')
            _dateType = (request.query_params.get('dateType', '') or 'created').lower()
            if _tenantKey:
                tenantKeys = [_tenantKey]
            else:
                tenantKeys = list(self.activeTenantKeys)
                tenantKeys.append('GLOBAL')
            fromCreatedDate = toCreatedDate = fromUpdatedDate = toUpdatedDate = None
            if _fromDate:
                fromCreatedDate = self._parse_query_iso_datetime(_fromDate)
                fromUpdatedDate = fromCreatedDate
            if _toDate:
                toCreatedDate = self._parse_query_iso_datetime(_toDate)
                toUpdatedDate = toCreatedDate
            if _dateType == 'updated':
                fromCreatedDate = toCreatedDate = None
            else:
                fromUpdatedDate = toUpdatedDate = None
            actionFilter = _action if _action else None
            statusFilter = _status if _status else None
            rows = []
            for tenantKey in tenantKeys:
                templates = self.cacheService.getRefereeTemplates(
                    tenantKey=tenantKey,
                    mobileNo=None,
                    action=actionFilter,
                    status=statusFilter,
                    from_created=fromCreatedDate,
                    to_created=toCreatedDate,
                    from_updated=fromUpdatedDate,
                    to_updated=toUpdatedDate,
                    forceReload=True
                )
                if templates and isinstance(templates, dict):
                    for msgSid, t in templates.items():
                        row = dict(t) if isinstance(t, dict) else {}
                        row['msgSid'] = msgSid
                        row['tenantKey'] = tenantKey
                        if row.get('data'):
                            row['data'] = jsonHelper.save_to_json(row.get('data'))
                        rows.append(row)
            rows.sort(key=lambda x: x.get('created', ''), reverse=True)
            rowsJson = jsonHelper.preJsonSetToDynamoDb(rows)
            content = {"data": rowsJson, "success": True}
            return JSONResponse(content=content, status_code=200, headers={"Content-Type": "application/json"})
        except Exception as ex:
            self.logger.error(f'Error in pwaGetRefereeTemplates: {ex}', exc_info=True)
            return JSONResponse(
                content={"data": [], "success": False, "error": str(ex)},
                status_code=500,
                headers={"Content-Type": "application/json"}
            )

    async def pwaSetRefereeTemplate(self, request: Request):
        """Admin-only: update a referee template status."""
        try:
            body = await request.json()
            tenantKey = body.get('tenantKey')
            mobileNo = body.get('mobileNo')
            msgSid = body.get('msgSid')
            newStatus = body.get('status')
            if not tenantKey or not mobileNo or not msgSid or not newStatus:
                return JSONResponse(
                    content={"success": False, "error": "tenantKey, mobileNo, msgSid and status are required"},
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )
            template = self.cacheService.getRefereeTemplates(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid)
            if not template or not isinstance(template, dict) or not msgSid in template:
                return JSONResponse(
                    content={"success": False, "error": "Template not found"},
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )
            template = template.get(msgSid)
            if template['status'] != newStatus and newStatus == 'created':
                template['retries'] = 0
            template['status'] = newStatus
            self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid, value=template)
            return JSONResponse(content={"success": True}, status_code=200, headers={"Content-Type": "application/json"})
        except Exception as ex:
            self.logger.error(f'Error in pwaSetRefereeTemplate: {ex}', exc_info=True)
            return JSONResponse(
                content={"success": False, "error": str(ex)},
                status_code=500,
                headers={"Content-Type": "application/json"}
            )

    def _parse_query_iso_datetime(self, raw: str):
        """Parse fromDate/toDate; apply unquote until stable so double-encoded query strings (%253A) still work."""
        if not raw or not str(raw).strip():
            return None
        s = str(raw).strip()
        prev = None
        while s != prev:
            prev = s
            s = unquote(s)
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        return datetime.fromisoformat(s)

    def pwaGetNotifications(self, request: Request):
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            _tenantKey = unquote(request.query_params.get('tenantKey', '')).strip()
            _target = (request.query_params.get('target') or '').strip()
            _id = unquote(request.query_params.get('id', '') or '').strip()
            _type = (request.query_params.get('type') or '').strip()  # notificationType
            _status = (request.query_params.get('status') or '').strip()
            _to_mobile = (request.query_params.get('to') or request.query_params.get('mobile') or '').strip()
            _fromDate = request.query_params.get('fromDate', '')
            _toDate = request.query_params.get('toDate', '')
            _dateType = (request.query_params.get('dateType', '') or 'created').lower()
            if _tenantKey:
                tenantKeys = [_tenantKey]
            else:
                tenantKeys = list(self.activeTenantKeys)
                tenantKeys.append('GLOBAL')
            fromCreatedDate = toCreatedDate = fromUpdatedDate = toUpdatedDate = None
            if _fromDate:
                fromCreatedDate = self._parse_query_iso_datetime(_fromDate)
                fromUpdatedDate = fromCreatedDate
            if _toDate:
                toCreatedDate = self._parse_query_iso_datetime(_toDate)
                toUpdatedDate = toCreatedDate
            if _dateType == 'updated':
                fromCreatedDate = toCreatedDate = None
            else:
                fromUpdatedDate = toUpdatedDate = None
            targetFilter = _target or None
            idFilter = _id or None
            typeFilter = _type or None
            statusFilter = _status or None
            toFilter = _to_mobile or None
            rows = []
            for tenantKey in tenantKeys:
                notifications = self.cacheService.getNotifications(
                    tenantKey=tenantKey,
                    target=targetFilter,
                    id=idFilter,
                    notificationType=typeFilter,
                    to=toFilter,
                    status=statusFilter,
                    from_created=fromCreatedDate,
                    to_created=toCreatedDate,
                    from_updated=fromUpdatedDate,
                    to_updated=toUpdatedDate,
                    forceReload=True
                )
                if notifications and isinstance(notifications, dict):
                    for key, n in notifications.items():
                        row = dict(n) if isinstance(n, dict) else {}
                        row['_key'] = key
                        row['tenantKey'] = tenantKey
                        if 'target' not in row and targetFilter:
                            row['target'] = targetFilter
                        rows.append(row)
            rows.sort(key=lambda x: x.get('created', ''), reverse=True)
            rowsJson = jsonHelper.preJsonSetToDynamoDb(rows)
            content = {"data": rowsJson, "success": True}
            return JSONResponse(content=content, status_code=200, headers={"Content-Type": "application/json"})
        except Exception as ex:
            self.logger.error(f'Error in pwaGetNotifications: {ex}', exc_info=True)
            return JSONResponse(
                content={"data": [], "success": False, "error": str(ex)},
                status_code=500,
                headers={"Content-Type": "application/json"}
            )

    async def pwaSetNotification(self, request: Request):
        """Admin-only: update a notification status."""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            body = await request.json()
            tenantKey = body.get('tenantKey')
            target = body.get('target')
            id_ = body.get('id')
            notificationType = body.get('notificationType') or body.get('type')
            to = body.get('to') if body.get('to') else None
            timestamp = body.get('timestamp')
            newStatus = body.get('status')
            if not tenantKey or not target or not id_ or not notificationType or timestamp is None or not newStatus:
                return JSONResponse(
                    content={"success": False, "error": "tenantKey, target, id, notificationType, to, timestamp and status are required"},
                    status_code=400,
                    headers={"Content-Type": "application/json"}
                )
            notification = self.cacheService.getNotifications(tenantKey=tenantKey, target=target, id=id_, notificationType=notificationType, to=to, timestamp=int(timestamp), forceReload=True)
            if not notification or not isinstance(notification, dict):
                return JSONResponse(
                    content={"success": False, "error": "Notification not found"},
                    status_code=404,
                    headers={"Content-Type": "application/json"}
                )
            notification = dict(notification)
            notification['status'] = newStatus
            self.cacheService.setNotification(tenantKey=tenantKey, target=target, id=id_, notificationType=notificationType, to=to, timestamp=int(timestamp), value=notification)
            return JSONResponse(content={"success": True}, status_code=200, headers={"Content-Type": "application/json"})
        except Exception as ex:
            self.logger.error(f'Error in pwaSetNotification: {ex}', exc_info=True)
            return JSONResponse(
                content={"success": False, "error": str(ex)},
                status_code=500,
                headers={"Content-Type": "application/json"}
            )
    
    async def myWebhook(self, request:Request):
        try:
            now = helpers.localNow()
            data = await request.json()
            self.logger.info(f'myWebhook data={data}')
            message = data.get('message')
            sender = data.get('sender')
            recipients = data.get('recipients')
            gamePortalCodePrefix = 'הסיסמה למשחק'
            if 'הוא קוד האימות שלך לפורטל השופטים' in message:
                type = '2FA_PortalCode'
            elif gamePortalCodePrefix in message:
                type = 'GamePassword'
            else:
                type = None
            
            if type in ('2FA_PortalCode', 'GamePassword'):
                if isinstance(recipients, str):
                    recipients = [recipients]
                for recipient in recipients:
                    mobileNo = MessagingService.adjustMobileNo(mobileNo=(recipient or ''))
                    receipientDetail = self.globalRefereesByMobile.get(mobileNo)
                    if receipientDetail:
                        if type == '2FA_PortalCode':
                            portalCodeMatch = re.search(r'\d+', message)
                            portalCode = portalCodeMatch.group(0) if portalCodeMatch else None
                            if portalCode:
                                portalCodeObj = { '2FA_PortalCode': portalCode, '2FA_PortalCodeDatetime': now }
                                successResponse = False
                                initiatedManually = True
                                for tenantKey in receipientDetail.get('activeTenantKeys', []):
                                    successResponse = True                            
                                    _2FA_PortalCode_RequestDatetime = self.cacheService.getCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, propertyName='2FA_PortalCode_RequestDatetime')
                                    if not _2FA_PortalCode_RequestDatetime:
                                        continue
                                    _2FA_PortalCode_ElapsedTime = now - _2FA_PortalCode_RequestDatetime
                                    if _2FA_PortalCode_ElapsedTime > timedelta(seconds=30):
                                        self.logger.info(f'myWebhook received manual requested portal code {portalCode}')
                                        continue
                                    self.logger.info(f'myWebhook tenantKey={tenantKey} mobileNo={mobileNo} received portal code {portalCode} from {sender}')
                                    self.cacheService.setCachedKeyVal(tenantKey=tenantKey, mobileNo=mobileNo, value=portalCodeObj, propertyName='2FA_PortalCode', ttlSeconds=1*60)
                                    initiatedManually = False
                                
                                if successResponse:
                                    if initiatedManually:
                                        return JSONResponse(content={"success": True, "message": "Portal code received, initiated manually"}, status_code=200)
                                    else:
                                        return JSONResponse(content={"success": True, "message": "Portal code received, initiated by service"}, status_code=200)
                                else:
                                    return JSONResponse(content={"success": False, "message": "Something went wrong with the portal code"}, status_code=202)
                            else:
                                self.logger.warning(f'myWebhook: Could not extract portal code from message: {message}')
                        
                        elif type == 'GamePassword':
                            tenantKey = [tenantKey for tenantKey in self.activeTenantKeys if '#football#' in tenantKey][0]
                            messageParts = message.split(':')
                            if len(messageParts) < 3:
                                self.logger.warning(f'myWebhook: Could not extract game password from message: {message}')
                                return JSONResponse(content={"success": False, "message": "Could not extract game password from message"}, status_code=202)
                            gamePassword = messageParts[2].strip()
                            if gamePassword:
                                gameTitle = None
                                pendingGames = await self.getRefereeGames(mobileNo=mobileNo, tenantKey=tenantKey, includeArchived=False, includeRemoved=False, fromDate=datetime.now(), toDate=datetime.now().date() + timedelta(days=1))
                                if False and pendingGames and len(pendingGames) > 0:
                                    game = pendingGames[0]
                                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=game)
                                    gameDetail['gamePassword'] = gamePassword
                                    gameTitle = gameDetail.get('gameTitle')
                                    self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], gamePk=gameDetail['gamePk'], value=gameDetail)
                                else:
                                    gameTitle = message[message.find(gamePortalCodePrefix)+len(gamePortalCodePrefix):].strip()
                                    # Extract game title (everything before the last colon)
                                    last_colon_index = gameTitle.rfind(':')
                                    if last_colon_index != -1:
                                        gameTitle = gameTitle[:last_colon_index].strip()
                                await self.messagingService.sendGamePortalCodeMessage(toMobile=mobileNo, toName=receipientDetail.get('name') or '', gameTitle=gameTitle, portalCode=gamePassword)
                                return JSONResponse(content={"success": True, "message": "Game password received"}, status_code=200)
                            else:
                                self.logger.warning(f'myWebhook: Could not extract game password from message: {message}')
                                return JSONResponse(content={"success": False, "message": "Could not extract game password from message"}, status_code=202)
                    break
            return JSONResponse(content={"success": False, "error": "Bad Request"}, status_code=400)
        except ClientDisconnect:
            # Caller closed the connection before the body was fully read (timeouts, retries, load balancers).
            self.logger.info('myWebhook: client disconnected before request body was received')
            raise
        except Exception as ex:
            self.logger.error(f'Error in myWebhook', ex)
            return JSONResponse(content={"success": False, "error": str(ex)}, status_code=500)

    #region incoming webhooks
    async def approveGame(self, mobileNo, gameId, msgSid=None):
        """Queue approve-game template for referee process (WhatsApp / PWA)."""
        self.logger.info(f'approveGame mobileNo: {mobileNo}, gameId: {gameId}')
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        if not gameDetail:
            return f"{helpers.localNow()} המשחק {gameId} לא נמצא במערכת"
        tenantKey = gameDetail.get('tenantKey')
        if not tenantKey:
            return f"{helpers.localNow()} לא נמצאה עונה למשחק"
        msgSid = msgSid or str(uuid.uuid4())[:16]
        self.cacheService.setRefereeTemplate(
            tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid,
            value={'action': 'approveGame', 'gameId': gameId, 'status': 'created'})
        title = gameDetail.get('gameTitle') or gameId
        return f"{helpers.localNow()} הבקשה לאישור המשחק {title} התקבלה בהצלחה"

    async def declineGame(self, mobileNo, gameId, msgSid=None):
        """Queue decline-game template for referee process (WhatsApp declinegameid + PWA reject)."""
        self.logger.info(f'declineGame mobileNo: {mobileNo}, gameId: {gameId}')
        gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
        if not gameDetail:
            return f"{helpers.localNow()} המשחק {gameId} לא נמצא במערכת"
        tenantKey = gameDetail.get('tenantKey')
        msgSid = msgSid or str(uuid.uuid4())[:16]
        self.cacheService.setRefereeTemplate(
            tenantKey=tenantKey, mobileNo=mobileNo, msgSid=msgSid,
            value={'action': 'declineGame', 'gameId': gameId, 'status': 'created'})
        return f"{helpers.localNow()} הבקשה לדחיית המשחק התקבלה בהצלחה"

    async def incomingWebhookFromTwilioImmediateResponse(self, backgroundTasks: BackgroundTasks, request:Request):
        backgroundTasks.add_task(self.messagingService.twilioIncomingWebhook, self.incomingWebhook, True, request)
        response = MessagingResponse()
        return str(response), 200  

    async def authenticateTwilioRequest(self, request:Request, x_twilio_signature: str = Header(None)):
        await self.messagingService.twilioClient.authenticateTwilioRequest(request=request)

    async def incomingWebhookFromTwilio(self, request:Request):
        response =  await self.messagingService.twilioIncomingWebhookAsync(incomingWebhookCallback=self.incomingWebhook, alwaysSendMessage=False, request=request)
        return Response(content=str(response[0]), status_code=int(response[1]), media_type="application/xml")

    async def authenticateGreenApiRequest(self, request:Request, x_twilio_signature: str = Header(None)):
        await self.messagingService.greenApiClient.authenticateGreenApiRequest(request=request)

    async def incomingWebhookFromGreenApi(self, request:Request):
        result = await self.messagingService.greenApiIncomingWebhook(incomingWebhookCallback=self.incomingWebhook, request=request)
        return JSONResponse(content=result[0], status_code=result[1])

    async def incomingWebhookFromManychat(self, request:Request):
        result = await self.messagingService.manychatIncomingWebhook(incomingWebhookCallback=self.incomingWebhook, request=request)
        return JSONResponse(content=result[0], status_code=result[1], media_type=result[2])

    async def incomingWebhookFromMeta_GET(
        self,
        mode: str = Query(..., alias="hub.mode"),
        challenge: str = Query(..., alias="hub.challenge"),
        verify_token: str = Query(..., alias="hub.verify_token")):
        #data = await request.json()  # Get webhook payload
        #result = await self.messagingService.manychatIncomingWebhook(data=data, incomingWebhookCallback=self.incomingWebhook, request=request)
        #return JSONResponse(content=result[0], status_code=result[1], media_type=result[2])
        # --- Webhook Verification ---
        # This is the part that handles the initial handshake from Meta.
        """
        Handles Meta's webhook verification request.

        When you configure your webhook in the Meta for Developers dashboard,
        Meta will send a GET request to this endpoint.

        This function checks if the verify_token matches and responds with
        the challenge code to complete the handshake.
        """
        self.logger.info("Webhook verification request received:")
        self.logger.info(f"Mode: {mode}")
        self.logger.info(f"Challenge: {challenge}")
        self.logger.info(f"Verify Token: {verify_token}")

        # Check if the mode and token are correct - In use only for registering webhook
        if mode == "subscribe" and verify_token == os.getenv('metaVerifyToken'):
            self.logger.info("Meta Webhook verified successfully!")
            # Respond with the challenge token
            return Response(content=challenge, media_type="text/plain", status_code=200)
        else:
            self.logger.info("Meta Webhook verification failed.")
            # Respond with an error if the tokens do not match
            raise HTTPException(status_code=403, detail="Verification token does not match")

    async def authenticateMetaRequest(self, request:Request):
        await self.messagingService.metaClient.authenticateMetaRequest(request=request)

    async def authenticateTelegramRequest(self, request:Request):
        await self.messagingService.telegramClient.authenticateTelegramRequest(request=request)

    async def incomingWebhookFromMeta_POST(self, request:Request):
        data = await request.json()  # Get webhook payload
        self.logger.info(f"incomingWebhookFromMeta_POST data={data}")
        result = await self.messagingService.metaIncomingWebhook(incomingWebhookCallback=self.incomingWebhook, request=request)
        return JSONResponse(content=result[0], status_code=result[1], media_type=result[2])

    async def incomingWebhookFromTelegram(self, request: Request):
        result = await self.messagingService.telegramIncomingWebhook(incomingWebhookCallback=self.incomingWebhook, request=request)
        return JSONResponse(content=result[0], status_code=result[1], media_type=result[2] if len(result) > 2 else "application/json")

    async def incomingWebhook(self, incomingRequest, request:Request):
        self.logger.debug(f"incomingWebhook incomingRequest={incomingRequest}")
        if incomingRequest is None:
            self.logger.warning("incomingWebhook: incomingRequest is None")
            return {}
        if not isinstance(incomingRequest, dict):
            self.logger.warning(f"incomingWebhook: incomingRequest is not a dict: {type(incomingRequest)}")
            return {}
        skipAuthentication = incomingRequest.get('skipAuthentication', False)
        source = incomingRequest.get('source')
        currentMessageSid = incomingRequest.get('messageSid')
        if not currentMessageSid:
            currentMessageSid = str(uuid.uuid4())[:8]
            incomingRequest['messageSid'] = currentMessageSid
        fromMobile = incomingRequest.get('fromMobile')
        fromName = incomingRequest.get('fromName')
        fromChatGroupId = incomingRequest.get('fromChatGroupId')
        fromMobileNo = MessagingService.adjustMobileNo(mobileNo=(fromMobile or '').lstrip('whatsapp:')) if not skipAuthentication else fromMobile
        incomingRequest['fromMobile'] = fromMobileNo

        if not skipAuthentication and not fromMobileNo:
            self.logger.warning(
                f"incomingWebhook: missing fromMobileNo (cannot process); source={source} rawFrom={fromMobile!r}"
            )
            return {}

        fromAdmin = fromMobileNo == self.adminMobile
        fromBot = fromMobileNo in self.botMobileNumbers

        '''
        applyMobileNo = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=fromMobileNo, propertyName='admin_apply_selected_referee', onlyCache=True)
        if applyMobileNo:
            fromMobileNo = applyMobileNo
        '''
        toNumber = MessagingService.adjustMobileNo(incomingRequest.get('toMobile'))
        messageBody = incomingRequest.get('messageBody') or ''

        localNow = helpers.localNow()

        originalMessageSid = incomingRequest.get('originalMessageSid')
        originalMessage = None
        recentMessageSid = None
        customData = {}
        customDataAction = None
        customDataReference = None
        
        # reply not using reply to, find recent message with buttonId
        if not originalMessageSid:
            recentMessages = self.getRecentRefereeMessages(mobileNo=fromMobileNo, direction='TO', recentDays=1)
            for recentMessage in recentMessages.values():
                recentMessage = recentMessage or {}
                if recentMessage.get('created') and localNow - recentMessage['created'] < timedelta(seconds=5*60):# and recentMessage.get('buttonId'):
                    msgSid = recentMessage.get('msgSid')
                    customData = self.cacheService.getReferenceId(target='msgSid', id=msgSid)
                    if customData:
                        recentMessageSid = msgSid
                        originalMessageSid = msgSid
                        break

        if not isinstance(customData, dict):
            customData = {}

        if originalMessageSid:
            originalMessage = self.cacheService.getMessage(msgSid=originalMessageSid)
            raw_custom = self.cacheService.getReferenceId(target='msgSid', id=originalMessageSid)
            customData = raw_custom if isinstance(raw_custom, dict) else {}
            self.logger.info(f'originalMessageSid={originalMessageSid} recentMessageSid={recentMessageSid} customData={customData}')
            customDataAction = customData.get('action')
            customDataReference = customData.get('reference')
        buttonId = incomingRequest.get('buttonId')
        latitude = incomingRequest.get('latitude')
        longitude = incomingRequest.get('longitude')
        mediaFiles = incomingRequest.get('mediaFiles') or []

        tenantKey = 'GLOBAL'
        globalRefereeDetail = self.globalRefereesByMobile.get(fromMobileNo) or {}
        refereeActiveTenantKeys = globalRefereeDetail.get('activeTenantKeys') or []
        if len(refereeActiveTenantKeys) > 0:
            tenantKey = refereeActiveTenantKeys[0]

        fromDetails = {
            'mobileNo': fromMobileNo,
            'name': fromName,
            'chatGroupId': fromChatGroupId,
            'activeTenantKeys': refereeActiveTenantKeys
        }

        isIncomingMessage = await self.messagingService.incomingWebhookCheckWindow(source=source, fromMobileNo=fromMobileNo, request=request)
        if isIncomingMessage == False:
            return {}

        repliedAnswer = None
        repliedFileUrl = None
        repliedFileName = None
        repliedMediaType = None
        repliedAnswerPreview:bool = False
        repliedLocation:dict = None

        if not skipAuthentication and fromBot:
            self.logger.debug(f"ignored incomingRequest={incomingRequest}")
            return {}

        self.logger.info(f"incomingRequest={incomingRequest}")

        self.logger.info(f"Received message fromDetails={fromDetails} to={toNumber}: button_id={buttonId} originalMessageSid={originalMessageSid} recentMessageSid={recentMessageSid} custom_data={customData} custom_data_action={customDataAction} custom_data_reference={customDataReference} body='{messageBody}' latitude={latitude} longitude={longitude} media_files={mediaFiles}")
        self.logger.debug(f"Current reply SID: {currentMessageSid}")
        self.logger.debug(f"search for Referee")
        
        try:
            incomingRequest['archived'] = False
            self.cacheService.setRefereeMessage(mobileNo=fromMobileNo, direction='FROM', msgSid=currentMessageSid, value=incomingRequest)
            self.cacheService.setReferenceId(target='msgSid', id=currentMessageSid, value=fromMobileNo)
            
            msgLog = {
                'origin': 'user',
                'type': 'incomingWebhook',
                'from': fromMobileNo,
                'fromName': globalRefereeDetail.get('name') or fromName,
                'to': toNumber,
                'messageBody': messageBody,
                'button_id': buttonId,
                'currentMessageSid': currentMessageSid,
                'originalMessageSid': originalMessageSid,
                'recentMessageSid': recentMessageSid,
                'custom_data': customData,
                'custom_data_action': customDataAction,
                'custom_data_reference': customDataReference,
            }
            self.messagingService.msgLogger.info(msgLog)
            
            # Simulate
            if fromAdmin and messageBody:
                if messageBody.lower().startswith('simulate#'):
                    if len(messageBody.split('#')) != 3:
                        repliedAnswer = 'פרמטרים שגויים'
                    else:
                        fromAdmin = False
                        simulateMobileNo = MessagingService.adjustMobileNo(mobileNo=messageBody.split('#')[1])
                        messageBody = messageBody.split('#')[2]
                        _refereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=simulateMobileNo)
                        if _refereeDetail:
                            fromMobileNo = simulateMobileNo
                            globalRefereeDetail = _refereeDetail
                elif messageBody.lower().startswith('na\n'):
                    messageBody = messageBody[3:]
                    fromAdmin = False
                    self.logger.info(f"incomingWebhook fromAdmin after na: {messageBody}")

            if globalRefereeDetail:
                mobileNo = globalRefereeDetail['mobileNo']
                referee_webhook_file_path = f'{os.getenv("MY_DATA_FOLDER", "/run/data/")}referees/webhook/mobileNo{fromMobileNo}_{currentMessageSid}.json'
                helpers.validatePath(referee_webhook_file_path)
                jsonHelper.save_to_file(await request.form(), referee_webhook_file_path)

            action = ''
            actionValue = None
            if messageBody:
                if messageBody.startswith('**סיכום משחק**') or messageBody.startswith('*סיכום משחק*'):
                    action = 'סיכום משחק'
                    actionValue = messageBody
                else:
                    (action, actionValue) = self.classifyMessage(message=messageBody)

            # Ask to Join new Referee by Admin
            # Join Confirmation reply by Referee
            if messageBody == '/pair':
                self.logger.info(f"telegram pairing request={incomingRequest}")
                repliedAnswer = f'לחץ על הכפתור ושלח את ההודעה על מנת להתחבר למערכת'
                clientIdentifier = str(uuid.uuid4())
                value = {
                    'clientIdentifier': clientIdentifier,
                    'telegramId': incomingRequest.get('fromId'),
                    'telegramUsername': incomingRequest.get('fromUsername'),
                    'processed': False
                }
                self.cacheService.setKeyVal(key=f'clientIdentifier_{clientIdentifier}', value=value)
                queryString = f"pair_telegram_{clientIdentifier}"
                repliedFileUrl = self.messagingService.getWhatsAppUrl(text=queryString)
            
            elif buttonId and buttonId.lower().startswith('joinconfirmation_'):
                answer = buttonId.split('_')[1]
                repliedAnswer = await self.joinConfirmationReply(mobileNo=fromMobileNo, answer=answer)

            # Login Approval button click by Referee
            elif buttonId and buttonId.lower().startswith('approvelogin_'):
                verification_code = buttonId.split('_')[1]
                repliedAnswer = await self.handleLoginApproval(mobileNo=fromMobileNo, verification_code=verification_code)

            elif messageBody and messageBody.lower().startswith('pair_'):
                self.logger.warning(f"In incomingWebhook pair {messageBody}")
                if len(messageBody.split('_')) < 3:
                    repliedAnswer = 'פרמטרים שגויים'
                else:

                    if messageBody.split('_')[1] == 'pwa':
                        clientIdentifier = messageBody.split('_')[2]
                        sessionIdentifier = messageBody.split('_')[3]

                        mobileNo = fromMobileNo
                        
                        # allow admin to override mobile no
                        if fromAdmin and len(messageBody.split('_')) == 5:
                            mobileNo = messageBody.split('_')[4]

                        globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
                        if not globalRefereeDetail or not globalRefereeDetail.get('activeTenantKeys'):
                            repliedAnswer = f"{helpers.localNow()} {mobileNo} השופט לא נמצא במערכת, אנא פנה למנהל המערכת {self.adminMobile}"
                            #await self.messagingService.sendMessage(to=self.adminMobile, message=f'{fromName}, נייד {mobileNo}, {repliedAnswer}')
                        else:
                            # Clean mobile number by removing '-', '+', and ' ' characters using regex
                            await self.pwaUpdateClientIdentifiers(clientIdentifier=clientIdentifier, sessionIdentifier=sessionIdentifier, mobileNo=mobileNo, status='active')

                            self.logger.warning(f"In incomingWebhook before generateJwtTokens")
                            token_data = await self.generateJwtTokens(request=request, clientIdentifier=clientIdentifier, mobileNo=mobileNo)

                            # Check if client is connected via WebSocket
                            self.logger.warning(f"In incomingWebhook before is_client_connected")
                            if self.websocketManager.is_client_connected(clientIdentifier):
                                # Send JWT token pair immediately
                                self.logger.warning(f"In incomingWebhook sending jwt token pair to {clientIdentifier} {token_data}")
                                await self.websocketManager.send_jwt_token(
                                    clientIdentifier, 
                                    token_data['access_token'], 
                                    token_data['refresh_token'],
                                    token_data['access_expires_in'],
                                    token_data['refresh_expires_in']
                                )
                                repliedAnswer = 'הזדהות אושרה בהצלחה - JWT נשלח'
                            else:
                                # Store both tokens for when client connects
                                self.setPendingJwtToken(clientIdentifier, token_data)
                                repliedAnswer = 'הזדהות אושרה בהצלחה - המתן לחיבור PWA'

                            clientInfo = self.cacheService.getClientIdentifier(clientIdentifier=clientIdentifier)
                            if not clientInfo:
                                self.logger.warning(f"In incomingWebhook clientIdentifier {clientIdentifier} not found")
                            
                    elif messageBody.split('_')[1] == 'telegram':
                        clientIdentifier = messageBody.split('_')[2]
                        value = self.cacheService.getKeyVal(key=f'clientIdentifier_{clientIdentifier}')
                        if not isinstance(value, dict):
                            if value is not None:
                                self.logger.warning(f"incomingWebhook pair telegram: clientIdentifier key expected dict, got {type(value)}")
                            value = None
                        if value:
                            telegramId = value.get('telegramId')
                            if value.get('processed') == True:
                                repliedAnswer = 'הזדהות כבר נעשתה'
                            else:
                                value['processed'] = True
                                self.cacheService.setKeyVal(key=f'clientIdentifier_{clientIdentifier}', value=value)
                                telegramUsername = value.get('telegramUsername')
                                self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=fromMobileNo, propertyName='telegramId', value=telegramId)
                                self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=fromMobileNo, propertyName='telegramUsername', value=telegramUsername)
                                self.cacheService.setKeyVal(key=f'telegramUserId_{telegramId}', value=fromMobileNo)
                                repliedAnswer = f'טלגרם הזדהה בהצלחה, נייד: {fromMobileNo}'
                            self.messagingService.telegramClient.sendMessage(chatId=telegramId, message=repliedAnswer, replyToMessageId=originalMessageSid)

                    _pairGrd = globalRefereeDetail if isinstance(globalRefereeDetail, dict) else {}
                    activeTenantKeys = _pairGrd.get('activeTenantKeys', [])
                    refereeIsInActive = False
                    for tenantKey in activeTenantKeys:
                        tenantRefereeDetail = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=fromMobileNo)
                        if not tenantRefereeDetail or tenantRefereeDetail.get('status') != 'active':
                            refereeIsInActive = True
                            break

                    if not fromAdmin and refereeIsInActive == True:
                        globalRefereeDetail = globalRefereeDetail if isinstance(globalRefereeDetail, dict) else {}
                        if globalRefereeDetail.get('status') != 'active':
                            promptButtons = [
                                {
                                    "sub_type": "quick_reply",
                                    "id": "activateReferee_yes",
                                    "text": "אישור"
                                },
                                {
                                    "sub_type": "quick_reply",
                                    "id": "activateReferee_no",
                                    "text": "דחה"
                                }
                            ]
                            customData = {
                                'action': 'activateReferee',
                                'mobileNo': fromMobileNo,
                            }
                            self.messagingService.sendInteractiveMessage(to=self.adminMobile, question=f'האם להפעיל התחברות של השופט {fromName or globalRefereeDetail.get("name")} {fromMobileNo} למערכת ?', promptButtons=promptButtons, customData=customData)

            # Activate Referee by Admin
            elif buttonId and (buttonId.lower().startswith('activateref_') or buttonId.lower().startswith('answer_activatereferee_') and customData.get('action') == 'activateReferee'):
                if buttonId.lower().startswith('activateref_'):
                    inputMobileNo = buttonId.split('_')[1]
                    approveAnswer = 'yes'
                else:
                    inputMobileNo = customData.get('mobileNo')
                    approveAnswer = buttonId.split('_')[2]
                
                if approveAnswer == 'yes':
                    repliedAnswer = await self.activateByMobileNo(mobileNo=inputMobileNo)
                else:
                    repliedAnswer = 'התחברות של השופט נדחתה'

            # Request to Approve Game by Referee
            elif globalRefereeDetail \
                and buttonId and buttonId == 'approvegameid':
                gameId = customData.get('gameId')
                repliedAnswer = await self.approveGame(mobileNo=fromMobileNo, gameId=gameId, msgSid=currentMessageSid)

            elif globalRefereeDetail \
                and buttonId and buttonId == 'declinegameid':
                gameId = customData.get('gameId')
                repliedAnswer = await self.declineGame(mobileNo=fromMobileNo, gameId=gameId, msgSid=currentMessageSid)

            elif buttonId and customDataAction == 'locationUpdateContext':
                repliedAnswer = await self.findGameFieldAndReply(fromDetails=fromDetails, originalMsgSid=currentMessageSid, customData=customData, buttonId=buttonId)

            elif buttonId and customDataAction == 'fieldUpdate':
                repliedAnswer = await self.findGameFieldAndReply(fromDetails=fromDetails, originalMsgSid=originalMessageSid, customData=customData, buttonId=buttonId)

            elif buttonId and customDataAction == 'mediaFileSelection':
                # Clear any pending media group for this user since we're processing now
                if fromMobileNo in self.pending_media_groups:
                    pending_group = self.pending_media_groups.pop(fromMobileNo)
                    # Cancel timeout task if it exists
                    if 'timeout_task' in pending_group and pending_group.get('timeout_task'):
                        timeout_task = pending_group['timeout_task']
                        if not timeout_task.done():
                            timeout_task.cancel()
                            self.logger.info(f"📄 Cancelled timeout task for {fromMobileNo} when processing media file selection")
                if customDataReference == 'game':
                    repliedAnswer = await self.findGameFieldAndReply(fromDetails=fromDetails, originalMsgSid=originalMessageSid, customData=customData, buttonId=buttonId)
                else:
                    repliedAnswer = 'לא נמצאה פעולה מתאימה'

            elif buttonId and buttonId.startswith('answer_skipAbortRun_') and customDataAction == 'skipAbortRun':
                answer = buttonId.split('_')[2]
                self.cacheService.setCachedKeyVal(tenantKey=customData.get('tenantKey'), mobileNo=customData.get('mobileNo'), value=answer, propertyName=f'skipAbortRun_{customData.get("objType")}')
                repliedAnswer = 'תשובתך נקלטה'

            #use agent
            if not repliedAnswer:
                if globalRefereeDetail \
                        and messageBody \
                        and self.schedule_agent \
                        and self.schedule_agent.should_handle(fromMobileNo):
                    try:
                        _src = (source or "").lower()
                        if _src == "telegram":
                            _channel = "telegram"
                        elif _src == "push":
                            _channel = "push"
                        else:
                            _channel = "whatsapp"
                        self.logger.info(f"incomingWebhook schedule_agent should_handle: {fromMobileNo} messageBody: {messageBody} channel: {_channel}")
                        agent_reply = await self.schedule_agent.process(
                            mobileNo=fromMobileNo,
                            message=messageBody,
                            refereeDetail=globalRefereeDetail,
                            tenantKey=tenantKey,
                            latitude=latitude,
                            longitude=longitude,
                            channel=_channel,
                        )
                        if agent_reply:
                            repliedAnswer = agent_reply
                    except Exception as e:
                        self.logger.error("ScheduleAgent error:", e)

            if not repliedAnswer:
                # Check if this is a poll vote
                if messageBody and messageBody.startswith('pollVote_') or buttonId and buttonId.startswith('answer_pollVote_') or customDataAction == 'pollVote':
                    # Process the vote
                    repliedAnswer = await self.pollService.process_vote_from_message(
                        messageBody=messageBody,
                        buttonId=buttonId,
                        customData=customData,
                        mobileNo=fromMobileNo,
                    )

                # Answer to Question Notification
                elif globalRefereeDetail \
                    and buttonId \
                    and buttonId.lower().startswith('answer_'):
                    answer = buttonId.lower().split('_')[1]
                    if customData and buttonId and customData.get(f'answer_{answer}'):
                        funcToCall = customData.get(f'answer_{answer}')
                        repliedAnswer = await eval(funcToCall)(fromMobileNo=fromMobileNo, message=customData, incomingRequest=incomingRequest)
                    else:
                        repliedAnswer = 'לא נמצאה פעולה מתאימה'

                elif action == 'הצטרפות':
                    repliedAnswer = await self.askToJoin(mobileNo=fromMobileNo)

                elif action in ('fields', 'מגרש'):
                    fieldToSearch = messageBody.replace(action, '')#.replace(actionValue, '')
                    fieldDetails = self.findFieldDetails(fromDetails=fromDetails, fieldToSearch=fieldToSearch, customData=customData)
                    if fieldDetails:
                        repliedAnswer = fieldDetails['details'].get('reply')
                        repliedLocation = fieldDetails['details'].get('location')
                        repliedAnswerPreview = True

                elif action == 'תמיכה':
                    name = fromName or globalRefereeDetail.get('name')
                    await self.messagingService.sendMessage(to=self.adminMobile, message=f'{name} פונה לתמיכה {fromMobileNo}')
                    repliedAnswer = f'{name}, יחזרו אליך בהקדם'

                elif True \
                    and messageBody \
                    and ('.txt' in action or '.pdf' in action):
                        repliedAnswer = f'נמצא הקובץ הבא: {action}'
                        repliedFileUrl = f'{self.docsServiceUrlBase}{quote(action)}'
                        repliedFileName = action

                elif True \
                    and messageBody \
                    and action.startswith('http'):
                        repliedAnswerPreview = True
                        repliedAnswer = f'נמצא הקישור הבא: {action}'

                elif action == 'בדיקות':
                    repliedAnswer = 'יש לקבוע תור לבדיקות רפואיות במכון 1, הבדיקות ממומנות על ידי איגוד השופטים, לא לשכוח להביא תוצאות בדיקות משלימות ותעודת חבר קופת חולים'
                    repliedAnswer += f'\nhttps://mahon1.com/סניפים/'


                elif globalRefereeDetail \
                    and (action == 'רישום' or buttonId == 'אישור'):
                    pass

                # Request to Update Password by Referee
                elif globalRefereeDetail \
                    and messageBody and messageBody.lower().startswith('תפריט'):
                    msgId = await self.messagingService.sendMenuContent(globalRefereeDetail)

                # Request to Update Password by Referee
                elif globalRefereeDetail \
                    and action == 'סיסמא':
                    url = f'{self.domainUrlBase}changePassword'
                    repliedAnswer = url

                    '''
                    if len(message_body.split('_')) != 2:
                        repliedAnswer = 'פרמטרים שגויים'
                    else:
                        refPassword = message_body.split('_')[1]
                        repliedAnswer = await self.changePasswordByRefId(refId, refPassword)
                    '''
                # Request to Get All Games by Referee
                elif globalRefereeDetail \
                    and (action.startswith('שיבוצים') or action.startswith('ביקורות')):
                    shortResponse = False
                    if action.startswith('שיבוצים') or buttonId and buttonId.startswith('games'):
                        objType = 'games'
                        if messageBody == 'שיבוצים קצר' or buttonId and buttonId == 'gamesShort':
                            shortResponse = True
                    else:
                        objType = 'reviews'
                    repliedAnswer = await self.handleRefereeData.getDataByMobileNo(mobileNo=fromMobileNo, objType=objType, shortResponse=shortResponse)
                
                elif globalRefereeDetail and action.startswith('יומן'):
                    calendarUrl = f'{self.apiServiceUrlBase}api/downloadIcsFile/{currentMessageSid}'
                    repliedAnswer = f'לוח השנה בדרך אליך...\n{calendarUrl}'
                    repliedAnswerPreview = True
                    #repliedFileName = f'calendar_{fromMobileNo}.ics'
                    #repliedFileUrl = calendarUrl
                    #repliedMediaType = 'text/calendar'

                elif globalRefereeDetail and messageBody.startswith('הבא'):
                    objType = 'games'
                    now = helpers.localNow()
                    games = self.handleRefereeData.getRefereeGames(tenantKey=globalRefereeDetail['activeTenantKeys'], mobileNo=fromMobileNo, from_date=now)#, toDate=now.replace(hour=23, minute=59, second=59, microsecond=0))
                    repliedAnswer = 'לא נמצאו משחקים קרובים'
                    if games:
                        sortedGames = sorted(games.values(), key=lambda item: item.get('date'))
                        nextRefereeGame = sortedGames[0]
                        nextGameDetails = self.cacheService.getGameDetail(tenantKey=nextRefereeGame['tenantKey'], game=nextRefereeGame)
                        if nextGameDetails:
                            repliedAnswer = f'המשחק הבא הוא בתאריך {nextGameDetails.get("date")}'
                            repliedAnswer += f'\nמסגרת משחקים: {nextGameDetails.get("tournamentName")}'
                            repliedAnswer += f'\nמשחק: {nextGameDetails.get("gameTitle")}'
                            repliedAnswer += f'\nמגרש: {nextGameDetails.get("field")}'
                            repliedAnswer += f'\nסיבוב: {nextGameDetails.get("round")}'
                            repliedAnswer += f'\nמחזור: {nextGameDetails.get("fixture")}'

                elif globalRefereeDetail and messageBody.startswith('סע'):
                    objType = 'games'
                    now = helpers.localNow()
                    games = self.handleRefereeData.getRefereeGames(tenantKey=globalRefereeDetail['activeTenantKeys'], mobileNo=fromMobileNo, from_date=now)#, toDate=now.replace(hour=23, minute=59, second=59, microsecond=0))
                    repliedAnswer = 'לא נמצאו משחקים קרובים'
                    if games:
                        sortedGames = sorted(games.values(), key=lambda item: item.get('date'))
                        nextRefereeGame = sortedGames[0]
                        nextGameDetails = self.cacheService.getGameDetail(tenantKey=nextRefereeGame['tenantKey'], game=nextRefereeGame)
                        if nextGameDetails:
                            field = self.cacheService.get_field_by_name(tenantKey=nextGameDetails['tenantKey'], fieldName=nextGameDetails['field'])
                            if field:
                                fieldAddressDetails = field.get('addressDetails')
                                if fieldAddressDetails:
                                    repliedAnswer = f'המשחק הבא הוא במגרש {field.get("title")}\nכתובת המגרש היא {fieldAddressDetails.get("address")}'
                                    repliedAnswer += f'\n{fieldAddressDetails.get("wazeLink")}'

                # Request to Get Link for Games Dashboard
                elif globalRefereeDetail \
                    and action == 'מוניטור':
                    url = f'{self.rootServiceUrlBase}dashboard/{globalRefereeDetail["guid"]}'
                    repliedAnswer = url

                # Request to Get Link for Games Calendar
                elif globalRefereeDetail \
                    and messageBody and messageBody.startswith('לוח שיבוצים'):
                    url = f'{self.rootServiceUrlBase}calendar/{globalRefereeDetail["guid"]}'
                    repliedAnswer = url

                # Update field by location
                elif globalRefereeDetail \
                    and latitude and longitude:
                    repliedAnswer = await self.askLocationContext(fromMobileNo=fromMobileNo, originalMsgSid=currentMessageSid, latitude=latitude, longitude=longitude)

                elif globalRefereeDetail \
                    and action == 'מאשר' \
                    and originalMessage and originalMessage.get('message'):
                    urls = self.urlParser.find_urls(originalMessage.get('message'))
                    for url in urls:
                        urlInfo = self.urlParser.extract_url_info(url)
                        if urlInfo.get('domain') == 'api.refereex.com':
                            gameId = urlInfo.get('path').split('/')[3]
                            repliedAnswer = await self.approveGame(mobileNo=fromMobileNo, gameId=gameId, msgSid=currentMessageSid)
                            break

                elif globalRefereeDetail \
                    and action == 'אופס':
                    repliedAnswer = 'לא נמצא ההקשר'
                    recentMessages = self.getRecentRefereeMessages(mobileNo=fromMobileNo, direction='TO', recentDays=1)
                    for msgSid1, recentMessage in recentMessages.items():
                        if recentMessage.get('created') and localNow - recentMessage['created'] < timedelta(seconds=5*60) and recentMessage.get('buttonId') and recentMessage['buttonId'].startswith('approvegameid_'):
                            repliedAnswer = await self.cancelGameApproval(mobileNo=fromMobileNo)
                            break

                elif globalRefereeDetail \
                    and action == 'סיכום משחק':
                    repliedAnswer = await self.postGameUpdate(mobileNo=fromMobileNo, msgSid=currentMessageSid, summary=messageBody)

                elif globalRefereeDetail \
                    and action == 'מחוז':
                    repliedAnswer = await self.updateArea(tenantKey=tenantKey, mobileNo=fromMobileNo, area=messageBody)

                elif len(mediaFiles) > 0:
                    # Check if there are pending media files from this user within the time window
                    grouped_media_files = await self._groupMediaFilesIfWithinWindow(
                        mobileNo=fromMobileNo,
                        new_media_files=mediaFiles,
                        current_message_sid=currentMessageSid,
                        current_timestamp=localNow
                    )
                    
                    self.logger.info(f"📄 len(mediaFiles) > 0 grouped_media_files: {grouped_media_files}")
                    if grouped_media_files:
                        # Use grouped media files (multiple pages) - process immediately
                        await self.askMediaFileContext(
                            fromDetails=fromDetails,
                            originalMsgSid=grouped_media_files['messageSid'],
                            media_files=grouped_media_files['mediaFiles']
                        )
                    else:
                        # Check if we just created a new pending group (single file or first in group)
                        # If so, schedule a timeout to process it if no more files arrive
                        self.logger.info(f"📄 len(mediaFiles) > 0 Check if fromMobileNo in self.pending_media_groups: {fromMobileNo} {self.pending_media_groups}")
                        if fromMobileNo in self.pending_media_groups:
                            pending_group = self.pending_media_groups[fromMobileNo]
                            # Only schedule timeout if there's no existing timeout task or it's done
                            if 'timeout_task' not in pending_group or pending_group.get('timeout_task') is None or pending_group['timeout_task'].done():
                                self.logger.info(f"📄 len(mediaFiles) > 0 Scheduling new timeout task for {fromMobileNo}")
                                # Schedule background task to process after timeout
                                timeout_task = asyncio.create_task(self._processPendingMediaGroupAfterTimeout(
                                    mobileNo=fromMobileNo,
                                    fromDetails=fromDetails,
                                    timeout_seconds=self.media_grouping_window_seconds
                                ))
                                pending_group['timeout_task'] = timeout_task
                            else:
                                self.logger.info(f"📄 len(mediaFiles) > 0 Timeout task already exists for {fromMobileNo}, will be cancelled if new files arrive")

                elif fromAdmin or fromBot:
                    # Health by Admin
                    if action == 'health':
                        repliedAnswer = await self.health()

                    # Reminder for not approved Games by Admin
                    elif action == 'reminderforapproval':
                        inputMobileNo = None
                        if actionValue:
                            inputMobileNo = actionValue 
                        referees = None
                        if inputMobileNo:
                            referees = [ self.handleRefereeData.activeRefereeByRefId[inputMobileNo] ]
                        else:
                            referees = self.handleRefereeData.activeRefereeByRefId    
                        await self.messagingService.sendNewGameNotificationForWaiting(referees)

                    # Activate Referee by Admin
                    elif action == 'activate':
                        inputMobileNo = actionValue
                        repliedAnswer = await self.activateByMobileNo(inputMobileNo)

                    # Deactivate Referee by Admin
                    elif action == 'deactivate':
                        inputMobileNo = actionValue
                        repliedAnswer = await self.deactivateByRefId(inputMobileNo)

                    # Ask to Join new Referee by Admin
                    elif action == 'join':
                        if actionValue is None:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            mobileNo = actionValue
                            repliedAnswer = await self.askToJoin(mobileNo=mobileNo)

                    # Send new joiner text by Admin
                    elif action == 'newjoinertext':
                        if actionValue is None:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            inputMobileNo = actionValue
                            repliedAnswer = await self.sendNewJoiner(mobileNo=inputMobileNo)

                    # Reload Referees
                    elif messageBody and messageBody.lower().startswith('reloadreferees'):
                        repliedAnswer = self.reloadReferees()

                    # Process RefId
                    elif action == 'process':
                        if actionValue is None:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            processRedId = actionValue
                            repliedAnswer = await self.processMobileNo(request, processRedId)

                    # Send Reopen Window reminders by Admin
                    elif action == 'checkwindow':
                        if len(messageBody.split('_')) > 3:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            mobileNo = None
                            message = None
                            if len(messageBody.split('_')) >= 2:
                                mobileNo = messageBody.split('_')[1]
                                mobileNo = MessagingService.adjustMobileNo(mobileNo=messageBody.split('_')[1])
                            if len(messageBody.split('_')) == 3:
                                message = messageBody.split('_')[2]
                            result = await self.checkWindow(mobileNo=mobileNo, message=message)
                            repliedAnswer = f'total open windows {result[1]} out of {result[0]}'

                    # Force Send games/reviews messages to Referee by Admin
                    elif action == 'forcesend':
                        if len(messageBody.split('_')) != 3:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            inputMobileNo = messageBody.split('_')[1]
                            objType = messageBody.split('_')[2]
                            repliedAnswer = await self.forceSendByMobileNo(tenantKey=tenantKey, mobileNo=inputMobileNo, objType=objType, msgSid=currentMessageSid)

                    elif messageBody and messageBody.lower().startswith('test'):
                        if len(messageBody.split('_')) != 2:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            size = int(messageBody.split('_')[1])
                            repliedAnswer = f"{'A' * size} size={size}"

                    elif messageBody and messageBody.lower().startswith('logs'):
                        logs = await self.getServiceLogs(5)
                        logsJson = jsonHelper.save_to_json(logs)
                        repliedAnswer = logsJson
                    
                    elif messageBody and messageBody.lower().startswith('summary'):
                        await self.handleRefereeData.collectGamesSummary()

                    elif action == 'refreshleaguestables':
                        leagueName = ''
                        if actionValue:
                            leagueName = actionValue
                        repliedAnswer = await self.refreshLeaguesTables(leagueName=leagueName)

                    # Reset reminders
                    elif messageBody and messageBody.lower().startswith('resetreminders_'):
                        if len(messageBody.split('_')) < 2:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            inputMobileNo = messageBody.split('_')[1]
                            hours = 2
                            if len(messageBody.split('_')) == 3:
                                hours = Decimal(messageBody.split('_')[2])
                            repliedAnswer = await self.resetReminders(mobileNo=inputMobileNo, hours=hours)

                    elif messageBody and messageBody.lower().startswith('text_'):
                        if len(messageBody.split('_')) < 3:
                            repliedAnswer = 'פרמטרים שגויים'
                        else:
                            mobileNo = MessagingService.adjustMobileNo(messageBody.split('_')[1])
                            recentMessage = messageBody.split('_')[2]
                            await self.messagingService.sendMessage(to=mobileNo, message=recentMessage)
                    else:
                        repliedAnswer = 'טקסט לא מזוהה'
                elif globalRefereeDetail \
                        and messageBody \
                        and self.schedule_agent \
                        and self.schedule_agent.should_handle(fromMobileNo):
                    try:
                        _src = (source or "").lower()
                        if _src == "telegram":
                            _channel = "telegram"
                        elif _src == "push":
                            _channel = "push"
                        else:
                            _channel = "whatsapp"
                        self.logger.info(f"incomingWebhook schedule_agent should_handle: {fromMobileNo} messageBody: {messageBody} channel: {_channel}")
                        agent_reply = await self.schedule_agent.process(
                            mobileNo=fromMobileNo,
                            message=messageBody,
                            refereeDetail=globalRefereeDetail,
                            tenantKey=tenantKey,
                            latitude=latitude,
                            longitude=longitude,
                            channel=_channel,
                        )
                        if agent_reply:
                            repliedAnswer = agent_reply
                    except Exception as e:
                        self.logger.error("ScheduleAgent error:", e)
                elif not fromBot:
                    llm_answered = False
                    if (
                        globalRefereeDetail
                        and messageBody
                        and self.llm_enhancer
                        and self.llmConfig.get('enabled', False)
                    ):
                        try:
                            llm_response = await self.llm_enhancer.process_complex_query(
                                message=messageBody,
                                referee_detail=globalRefereeDetail,
                            )
                            confidence_threshold = self.llmConfig.get('confidence_threshold', 0.7)
                            if llm_response.confidence > confidence_threshold and llm_response.answer:
                                repliedAnswer = llm_response.answer
                                llm_answered = True
                                self.logger.info(
                                    f"Using LLM response for referee natural message (confidence: {llm_response.confidence}, sources: {llm_response.sources})"
                                )
                                if self.llmConfig.get('log_interactions', False):
                                    self.log_llm_interaction(messageBody, llm_response)
                            else:
                                self.logger.debug(
                                    f"LLM response confidence too low: {llm_response.confidence} (threshold: {confidence_threshold})"
                                )
                        except Exception as ex:
                            self.logger.error(f"LLM enhancement error:", ex)
                    if not llm_answered:
                        if not repliedAnswer:
                            repliedAnswer = ''
                            if 'כל הכבוד' in messageBody:
                                repliedAnswer = 'תודה רבה על הפרגון שלך, את/ה מוזמן/ת להפיץ את הבשורה הלאה\n'
                            elif originalMessageSid:
                                repliedAnswer = 'מה פספסתי ?\n'
                            repliedAnswer += f'את/ה מתכתב/ת עם הבוט של RefereeX, שירות הודעות ועדכונים לשופטים,\nעל מנת לקבל מידע על השירות יש להשיב *מידע*\nעל מנת להצטרף למערכת יש להשיב *הצטרפות*'

            # Fallback LLM: only if nothing else produced a reply (repliedAnswer still empty), or admin got
            # טקסט לא מזוהה. When schedule_agent.should_handle ran but returned no text, repliedAnswer stays
            # empty and this invokes LLM once (the not fromBot branch is skipped because schedule elif matched).
            # No second LLM after a successful reply from schedule_agent or from the not fromBot LLM.
            if messageBody and (not repliedAnswer or repliedAnswer == 'טקסט לא מזוהה') \
                    and self.llm_enhancer:
                try:
                    # Check if LLM is enabled
                    if not self.llmConfig.get('enabled', False):
                        self.logger.debug("LLM integration disabled via configuration")
                    else:
                        # Admin / edge: no reply yet, or unrecognized admin command
                        llm_response = await self.llm_enhancer.process_complex_query(
                            message=messageBody,
                            referee_detail=globalRefereeDetail
                        )
                        
                        # Use LLM response if confidence is high enough
                        confidence_threshold = self.llmConfig.get('confidence_threshold', 0.7)
                        if llm_response.confidence > confidence_threshold and llm_response.answer:
                            repliedAnswer = llm_response.answer
                            self.logger.info(f"Using LLM response (confidence: {llm_response.confidence}, sources: {llm_response.sources})")
                            
                            # Log interaction if enabled
                            if self.llmConfig.get('log_interactions', False):
                                self.log_llm_interaction(messageBody, llm_response)
                        else:
                            self.logger.debug(f"LLM response confidence too low: {llm_response.confidence} (threshold: {confidence_threshold})")
                        
                except Exception as ex:
                    self.logger.error(f"LLM enhancement error:", ex)
        
        except Exception as ex:
            self.logger.error(f"Error processing complex query:", ex)
            raise
            #repliedAnswer = 'מצטער, יש בעיה טכנית. אנא נסה שוב מאוחר יותר.'

        replyTextForClient = None if repliedAnswer == INCOMING_WEBHOOK_REPLY_INTERACTIVE_ONLY else repliedAnswer
        self.logger.info(f'incoming result={replyTextForClient}')
        
        reply = {
            'repliedAnswer': replyTextForClient,
            'repliedFileUrl': repliedFileUrl,
            'repliedFileName': repliedFileName,
            'repliedMediaType': repliedMediaType,
            'repliedAnswerPreview': repliedAnswerPreview,
            'repliedLocation': repliedLocation,
        }
        if reply and isinstance(incomingRequest, dict):
            incomingRequest['reply'] = reply
            # Add downloaded media files info to the incoming request
        if fromMobileNo:
            self.cacheService.setRefereeMessage(mobileNo=fromMobileNo, direction='FROM', msgSid=currentMessageSid, value=incomingRequest)

        if replyTextForClient:
            _refNameDict = globalRefereeDetail if isinstance(globalRefereeDetail, dict) else {}
            msgLog = {
                'origin': 'system',
                'type': 'incomingWebhook',
                'from': toNumber,
                'to': fromMobileNo,
                'toName': _refNameDict.get('name') or fromName,
                'messageBody': replyTextForClient,
                'originalMessageSid': currentMessageSid,
            }
            self.messagingService.msgLogger.info(msgLog)

        return reply
    #endregion incoming webhooks

    #region webhooks functions
    def classifyMessage(self, message, isPhone:bool=False):
        message = helpers.normalize_text(message)
        message = helpers.split_letters_digits(message)

        action = self.match_intent(message)
        if not action:
            return '', None

        if isPhone:
            phone = helpers.extract_phone_number(message)
            if phone:
                return action, phone

        season = helpers.extract_year_format(message)
        if season:
            return action, season

        number = helpers.extract_number(message)
        if number:
            return action, str(number)

        token = None
        if len(message.split(' ')) > 1:
            token = message.split(' ')[1]
        
        return action, token

    def normalize_intent_word(self, word):
        """Map any variant to its canonical intent"""
        for canonical, variants in self.INTENT_BASES.items():
            if variants is None:
                variants = list()
            variants.append(canonical)
            if word in variants:
                return canonical.lower()
            match = helpers.find_intuitive_matches(word, variants, cutoff=0.6)
            if match:
                return canonical
        return None

    def match_intent(self, text):
        words = text.split()

        # Join bigrams (e.g., "חוקת ילדים")
        bigrams = [" ".join([words[i], words[i + 1]]) for i in range(len(words) - 1)]

        candidates = words + bigrams

        bestMatchCanonical = None
        bestScore = -1
        for phrase in candidates:
            for canonical, value in self.intent_phrases.items():
                variants = value.get('variants')
                variants1 = list()
                if variants:
                    variants1 = variants.copy()
                variants1.append(canonical)
                if False and phrase in variants1:
                    return canonical
                match = helpers.find_intuitive_matches(phrase, variants1, cutoff=0.5)
                if match and match[1] > bestScore:
                    if value.get('type') == 'file':
                        bestMatchCanonical = value.get('file')
                    elif value.get('type') == 'url':
                        bestMatchCanonical = value.get('url')
                    else:
                        bestMatchCanonical = canonical
                    bestScore = match[1]
        
        return bestMatchCanonical

    def getRecentRefereeMessages(self, mobileNo:str, direction:str, recentDays:int=1):
        if not mobileNo:
            return {}
        recentMessages = self.cacheService.getRefereeMessages(mobileNo=mobileNo, direction=direction, recentDays=recentDays)
        if not isinstance(recentMessages, dict) or not recentMessages:
            return {}
        sortedMsgSids = helpers.sortDictByProperty(recentMessages, 'created', True)
        return sortedMsgSids
    
    async def askLocationContext(self, fromMobileNo, originalMsgSid, latitude, longitude):
        promptButtons = [
            {
                "sub_type": "quick_reply",
                "id": "locationContext_fieldUpdate",
                "text": "עדכון מיקום מגרש"
            },
            {
                "sub_type": "quick_reply",
                "id": "locationContext_originLocation",
                "text": "עדכון המוצא שלי"
            },
        ]
        
        customData = {
            'action': 'locationUpdateContext',
            'latitude': latitude,
            'longitude': longitude,
            'originalMsgSid': originalMsgSid
        }
        self.messagingService.sendInteractiveMessage(to=fromMobileNo, question=f'מה תרצה/י לעשות עם המיקום ששלחת ?', promptButtons=promptButtons, customData=customData, replyToMessageId=originalMsgSid)
        return ''

    def fieldUpdateReply(self, mobileNo, originalMsgSid, field, promptButtons:list, latitude, longitude, retry):
        customData = {
            'action': 'locationUpdateContext',
            'tenantKey': field and field['tenantKey'] or '',
            'fieldUpdate': field and field['fieldName'] or '',
            'latitude': latitude,
            'longitude': longitude,
            'retry': retry
        }
        self.messagingService.sendInteractiveMessage(to=mobileNo, question=f'האם אתה רוצה לעדכן את מיקום מגרש {field["fieldName"]} ?', promptButtons=promptButtons, customData=customData, replyToMessageId=originalMsgSid)

    async def _groupMediaFilesIfWithinWindow(self, mobileNo: str, new_media_files: list, current_message_sid: str, current_timestamp: datetime) -> dict | None:
        """
        Group multiple media files sent within a time window as one multi-page document.
        Returns grouped media files if time window expired, None if still waiting for more files.
        """
        # Check if there's a pending group for this user
        if mobileNo in self.pending_media_groups:
            pending_group = self.pending_media_groups[mobileNo]
            time_diff = (current_timestamp - pending_group['timestamp']).total_seconds()
            self.logger.info(f"📄 _groupMediaFilesIfWithinWindow: {mobileNo} time_diff: {time_diff} seconds")
            
            # If within the time window, add new files to the group
            if time_diff <= self.media_grouping_window_seconds:
                # Cancel the old timeout task since we're extending the window
                if 'timeout_task' in pending_group and pending_group['timeout_task']:
                    old_task = pending_group['timeout_task']
                    if not old_task.done():
                        old_task.cancel()
                        self.logger.info(f"📄 _groupMediaFilesIfWithinWindow: Cancelled old timeout task for {mobileNo}")
                
                pending_group['mediaFiles'].extend(new_media_files)
                pending_group['timestamp'] = current_timestamp
                self.logger.info(f"📄 _groupMediaFilesIfWithinWindow: Grouped media files for {mobileNo}: {len(pending_group['mediaFiles'])} pages total")
                return None  # Don't process yet, wait for more or timeout
            else:
                # Time window expired, return the pending group
                # Cancel timeout task if it exists
                if 'timeout_task' in pending_group and pending_group['timeout_task']:
                    old_task = pending_group['timeout_task']
                    if not old_task.done():
                        old_task.cancel()
                
                grouped = self.pending_media_groups.pop(mobileNo)
                # Remove timeout_task from the returned group
                grouped.pop('timeout_task', None)
                self.logger.info(f"📄 _groupMediaFilesIfWithinWindow: Processing grouped media files for {mobileNo}: {len(grouped['mediaFiles'])} pages")
                return grouped
        
        # No pending group, create a new one
        self.pending_media_groups[mobileNo] = {
            'mediaFiles': new_media_files.copy(),
            'timestamp': current_timestamp,
            'messageSid': current_message_sid,
            'timeout_task': None  # Will be set when scheduling the timeout
        }
        
        return None
    
    async def _processPendingMediaGroupAfterTimeout(self, mobileNo: str, fromDetails: dict, timeout_seconds: int):
        """
        Background task to process pending media group after timeout if no more files arrive.
        """
        try:
            self.logger.info(f"📄 _processPendingMediaGroupAfterTimeout: {mobileNo} timeout_seconds: {timeout_seconds} seconds")
            await asyncio.sleep(timeout_seconds)
            
            # Check if group still exists and hasn't been processed
            self.logger.info(f'📄 _processPendingMediaGroupAfterTimeout: Check if mobileNo in self.pending_media_groups: {mobileNo} {self.pending_media_groups}')
            if mobileNo in self.pending_media_groups:
                pending_group = self.pending_media_groups[mobileNo]
                time_diff = (helpers.localNow() - pending_group['timestamp']).total_seconds()
                self.logger.info(f"📄 Processing pending media group after timeout for {mobileNo} time_diff: {time_diff} seconds")
                
                # Only process if timeout has passed (no new files arrived)
                # Also verify this is still the same task (not cancelled and replaced)
                if time_diff >= timeout_seconds:
                    # Double-check the group still exists and this task is still valid
                    if mobileNo in self.pending_media_groups:
                        # Remove the group
                        processed_group = self.pending_media_groups.pop(mobileNo)
                        # Remove timeout_task from the group before processing
                        processed_group.pop('timeout_task', None)
                        self.logger.info(f"📄 Processing pending media group after timeout for {mobileNo}: {len(processed_group['mediaFiles'])} pages")
                        await self.askMediaFileContext(
                            fromDetails=fromDetails,
                            originalMsgSid=processed_group['messageSid'],
                            media_files=processed_group['mediaFiles']
                        )
                    else:
                        self.logger.info(f"📄 _processPendingMediaGroupAfterTimeout: Group for {mobileNo} was already processed/removed")
                else:
                    self.logger.info(f"📄 _processPendingMediaGroupAfterTimeout: Timeout not reached yet for {mobileNo} (time_diff={time_diff}), new files may have arrived")
            else:
                self.logger.info(f"📄 _processPendingMediaGroupAfterTimeout: Group for {mobileNo} no longer exists (may have been processed)")
        except asyncio.CancelledError:
            self.logger.info(f"📄 _processPendingMediaGroupAfterTimeout: Timeout task cancelled for {mobileNo} (new files arrived)")
            raise
    
    async def askMediaFileContext(self, fromDetails, originalMsgSid, media_files:list, retry:int=0):
        self.logger.info(f"📄 askMediaFileContext: Asking media file context for {fromDetails.get('mobileNo')} {originalMsgSid}: {len(media_files)} pages")
        mediaFileTypes = []
        promptButtons = []
        reference = None
        tenants = self.cacheService.getTenants()
        for tenantKey in fromDetails.get('activeTenantKeys'):
            tenant = tenants.get(tenantKey)
            if not tenant:
                continue
            tenantRefereeDetail = self.refereesByMobile[tenantKey].get(fromDetails.get('mobileNo'))
            if not tenantRefereeDetail:
                continue
            tenantMediaFileTypes = tenant.get('mediaFileTypes')
            for mediaFileTypeActionId, mediaFileDetail in tenantMediaFileTypes.items():
                if mediaFileTypeActionId in mediaFileTypes:
                    continue
                # Check if user roles intersect with media file required roles
                tenantRoles = set(tenantRefereeDetail.get('roles', []))
                requiredRoles = set(mediaFileDetail.get('roles', []))
                if mediaFileDetail.get('reference'):
                    reference = mediaFileDetail.get('reference')
                eligible = bool(tenantRoles & requiredRoles)  # Set intersection
                if not eligible:
                    continue
                mediaFileTypes.append(mediaFileTypeActionId)
                promptButtons.append(
                {
                    "sub_type": "quick_reply",
                    "id": f"mediaFileSelection_{mediaFileTypeActionId}",
                    "text": mediaFileDetail['title']
                })
        
        media_ids = [media_file['media_id'] for media_file in media_files]
        page_count = len(media_files)
        question = f'איזה מסמך שלחת ?' + (f' ({page_count} עמודים)' if page_count > 1 else '')
        
        customData = {
            'action': 'mediaFileSelection',
            'mediaFileSelection': media_ids,
            'reference': reference,
        }
        sortedPromptButtons = sorted(promptButtons, key=lambda x: (x.get('sorted', ''), x['text']))
        self.messagingService.sendInteractiveMessage(to=fromDetails.get('mobileNo'), question=question, promptButtons=sortedPromptButtons, interactiveType='list', customData=customData, replyToMessageId=originalMsgSid)
        return INCOMING_WEBHOOK_REPLY_INTERACTIVE_ONLY

    async def findGameFieldAndReply(self, fromDetails, originalMsgSid, customData, buttonId=None):
        mobileNo = fromDetails.get('mobileNo')
        globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
        tenantKeys = fromDetails.get('activeTenantKeys')
        if not isinstance(customData, dict):
            customData = {}
        customDataAction = customData.get('action')
        actionTag = 'gameId' if customDataAction == 'mediaFileSelection' else 'fieldUpdate'
        start = None
        limit = None
        if buttonId.startswith('answer_gameId_'):
            gameId = buttonId.split('_')[2]
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            tenantKey = gameDetail['tenantKey']
            internalGameId = gameDetail.get('internalGameId') or ''
            if internalGameId:
                internalGameId = f'_{internalGameId}'
            fileType = customData['actionType'].split('_')[2]
            tag = f"{gameDetail.get('tenantKey')}/{fileType}{internalGameId}_{gameId}"
            mediaFiles = customData.get('mediaFileSelection', [])
            # Merge multiple pages into one PDF if there are multiple files
            saveAsOneFile = len(mediaFiles) > 1
            savedMediaFiles = await self.downloadMediaFilesAndStore(
                mobileNo=mobileNo,
                current_message_sid=originalMsgSid, 
                fileType=fileType,
                tag=tag, 
                mediaFiles=mediaFiles,
                saveAsOneFile=saveAsOneFile
            )
            category = None
            if savedMediaFiles:
                self.logger.info(f"📄 findGameFieldAndReply: savedMediaFiles: {savedMediaFiles}")
                for savedMediaFile in savedMediaFiles:
                    #tag = savedMediaFile['tag']
                    storage_path = savedMediaFile['storage_path']
                    category = savedMediaFile['category']

                    data = { 'storagePath!': storage_path }
                    template = { 'action': fileType, 'gameId': gameId, 'data': data, 'status': 'created' }
                    self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mobileNo, msgSid=originalMsgSid, value=template)

            return f'המסמך נשמר תחת {category or ""}/{tag}'

        elif buttonId == 'answer_gamemore':
            limit = int(customData.get('limit'))
            start = int(customData.get('start')) + limit
            customData['start'] = start
        
        elif buttonId == 'answer_locationContext_originLocation':
            latitude = customData.get('latitude')
            longitude = customData.get('longitude')
            value = {
                'latitude': latitude,
                'longitude': longitude, 
                'expiredBy': helpers.localNow() + timedelta(hours=5)
            }
            self.cacheService.setCachedKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, value=value, propertyName='originLocation')
            timestamp = int(time.time())
            self.cacheService.setRefereeLocation(mobileNo=mobileNo, timestamp=timestamp, value=value)
            
            pendingGames = await self.getRefereeGames(mobileNo=fromDetails.get('mobileNo'))
            for game in pendingGames:
                commuteReminderTimeInAdvance = globalRefereeDetail.get('commuteReminderTimeInAdvance')
                notifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='refereeLastReminder', to=mobileNo)
                for notification in notifications.values():
                    notification['reminderInHrs'] = commuteReminderTimeInAdvance
                    notification['status'] = 'created'
                    self.cacheService.setNotification(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='refereeLastReminder', to=mobileNo, timestamp=notification['timestamp'], value=notification)
            reply = f'מיקום המוצא שלך עודכן ל-5 שעות הקרובות עד {value.get('expiredBy')}'
            return reply

        elif buttonId.startswith('answer_fieldUpdate_'):
            gameId = buttonId.split('_')[2]
            gameDetail = self.cacheService.getGameDetailById(gameId=gameId)
            tenantKey = gameDetail['tenantKey']
            fieldName = gameDetail.get('field')
            field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldName)
            latitude = customData.get('latitude')
            longitude = customData.get('longitude')
            if longitude and latitude:
                field = self.updateFieldAddress(tenantKey=tenantKey, fieldName=fieldName, latitude=latitude, longitude=longitude)
                if field:
                    self.cacheService.setField(tenantKey=tenantKey, fieldName=fieldName, value=field)
                    repliedAnswer = f'מיקום מגרש {fieldName} עודכן'
                    repliedAnswer += f'\nנא בדיקתך {field["addressDetails"]["wazeLink"]}'
                    await self.messagingService.sendMessage(to=self.adminMobile, message=f'עדכון מיקום מגרש {fieldName} בוצע על ידי {fromDetails.get('mobileNo')} {fromDetails.get('name')}')
                    return repliedAnswer

        elif buttonId == 'answer_fieldTextSearch':
            customData['actionType'] = buttonId
            msgSid = await self.messagingService.sendMessage(to=fromDetails.get('mobileNo'), message=f'ניתן *להגיב להודעה* לרשום את שם המגרש ונמצא אותו יחד, לדוגמא: מגרש בלומפילד', replyToMessageId=originalMsgSid)
            if msgSid:
                self.cacheService.setReferenceId(target='msgSid', id=msgSid, value=customData)
                return INCOMING_WEBHOOK_REPLY_INTERACTIVE_ONLY

        elif buttonId == 'answer_yes':
            tenantKey = customData.get('tenantKey')
            fieldName = customData.get('fieldUpdate')
            field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldName)
            latitude = customData.get('latitude')
            longitude = customData.get('longitude')
            if longitude and latitude:
                field = self.updateFieldAddress(tenantKey=tenantKey, fieldName=fieldName, latitude=latitude, longitude=longitude)
                if field:
                    self.cacheService.setField(tenantKey=tenantKey, fieldName=fieldName, value=field)
                    repliedAnswer = f'מיקום מגרש {fieldName} עודכן'
                    repliedAnswer += f'\nנא בדיקתך {field["addressDetails"]["wazeLink"]}'
                    await self.messagingService.sendMessage(to=self.adminMobile, message=f'עדכון מיקום מגרש {fieldName} בוצע על ידי {fromDetails.get('mobileNo')} {fromDetails.get('name')}')
                    return repliedAnswer

        else:
            limit = 6
            start = 0
            customData['actionType'] = buttonId
            customData['limit'] = limit
            customData['start'] = start
        
        games = self.handleRefereeData.findMostRelevantGames(tenantKeys=tenantKeys, mobileNo=mobileNo, start=start, limit=limit+1)

        promptButtons = []
        for game in games[:limit]:
            gameDetail = game['gameDetail']
            tenantKey = gameDetail.get('tenantKey')
            fieldName = gameDetail.get('field')
            field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldName)
            if actionTag == 'gameId':
                buttonText = f"{gameDetail['tournamentName']}"
                buttonDescription = f"{gameDetail['gameTitle']}{' - ' + field['fieldName'] if field else ''}"
            else:
                buttonText = f"{field['fieldName']}"
                buttonDescription = f"{field['fieldName']} - {gameDetail['gameTitle']} {gameDetail['tournamentName']}"
            promptButtons.append(
                {
                    "sub_type": "quick_reply",
                    "id": f"{actionTag}_{game['gameId']}",
                    "text": buttonText,
                    "description": buttonDescription
                }
            )
        
        if False and len(games) > limit:
            promptButtons.append(
                {
                    "sub_type": "quick_reply",
                    "id": "gamemore",
                    "text": "עוד משחקים..."
                }
            )

        if customDataAction == 'locationUpdateContext':
            promptButtons.append(
                {
                    "sub_type": "quick_reply",
                    "id": "fieldTextSearch",
                    "text": "חפש מגרש לפי מלל"
                }
            )
        
        question = f'יש לבחור את המשחק הרלוונטי ?' if actionTag == 'gameId' else f'יש לבחור את המגרש הרלוונטי ?'
        self.messagingService.sendInteractiveMessage(to=mobileNo, question=question, promptButtons=promptButtons, interactiveType='list', customData=customData, replyToMessageId=originalMsgSid)
        return INCOMING_WEBHOOK_REPLY_INTERACTIVE_ONLY

    async def downloadMediaFilesAndStore(self, mobileNo, current_message_sid, fileType, tag, mediaFiles, saveAsOneFile=False):
        # Collect media files if any
        if len(mediaFiles) > 0:
            self.logger.debug(f"Received {len(mediaFiles)} files")
            try:
                tasks = []
                for media_file in mediaFiles:
                    media_id = media_file['media_id'] if isinstance(media_file, dict) else media_file
                    task = self.messagingService.metaClient.downloadMediaFile(media_id=media_id)
                    tasks.append(task)

                downloaded_media_infos = await asyncio.gather(*tasks)

                tasks = []
                for downloaded_media_info in downloaded_media_infos:
                    task = self.mediaFileCollector.save_media_file(tag=tag, fileType=fileType, mediaInfo=downloaded_media_info, fromMobileNo=mobileNo, currentMessageId=current_message_sid)
                    tasks.append(task)

                saved_media_files = await asyncio.gather(*tasks)

                if saveAsOneFile and len(saved_media_files) > 1:
                    # Merge multiple media files into one PDF
                    merged_pdf_file = await self._mergeMediaFilesToPDF(
                        saved_media_files=saved_media_files,
                        fileType=fileType,
                        tag=tag,
                        mobileNo=mobileNo,
                        current_message_sid=current_message_sid
                    )
                    if merged_pdf_file:
                        # Return the merged PDF file instead of individual files
                        return [merged_pdf_file]
                
                return saved_media_files

            except Exception as e:
                self.logger.error(f"Error collecting media files: {str(e)}")
        
        return None
    
    async def _mergeMediaFilesToPDF(self, saved_media_files: list, fileType: str, tag: str, mobileNo: str, current_message_sid: str) -> dict | None:
        """
        Merge multiple image files into one PDF document.
        
        Args:
            saved_media_files: List of saved media file info dictionaries
            tag: Tag for organizing files
            mobileNo: Mobile number of sender
            current_message_sid: Message SID
            
        Returns:
            Dictionary with merged PDF file info or None if merge failed
        """
        if not PDF_MERGE_AVAILABLE:
            self.logger.error("PDF merge libraries not available (PIL/reportlab)")
            return None
        
        try:
            # Filter only image files
            image_files = [
                f for f in saved_media_files 
                if f and f.get('extension', '').lower() in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            ]
            
            if len(image_files) == 0:
                self.logger.warning("No image files to merge into PDF")
                return None
            
            if len(image_files) == 1:
                # Only one image, no need to merge
                return image_files[0]
            
            self.logger.info(f"📄 Merging {len(image_files)} images into one PDF")
            
            # Generate merged PDF filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            merged_filename = f"{timestamp}_{mobileNo}_{fileType}_merged_{len(image_files)}pages.pdf"
            category = "documents"
            storage_path = os.path.join(self.mediaFileCollector.base_storage_path, category, tag, merged_filename)
            
            # Ensure directory exists
            helpers.validatePath(file=storage_path)
            
            # Create PDF with all images
            pdf_buffer = io.BytesIO()
            pdf_canvas = canvas.Canvas(pdf_buffer, pagesize=A4)
            
            for idx, image_file in enumerate(image_files):
                image_path = image_file.get('storage_path')
                if not image_path or not os.path.exists(image_path):
                    self.logger.warning(f"Image file not found: {image_file.get('filename')}")
                    continue
                
                try:
                    # Open image with PIL to get dimensions
                    with Image.open(image_path) as img:
                        img_width, img_height = img.size
                        
                        # Calculate scaling to fit A4 page (with margins)
                        page_width, page_height = A4
                        margin = 20  # 20 points margin
                        available_width = page_width - (2 * margin)
                        available_height = page_height - (2 * margin)
                        
                        # Calculate scale to fit image on page
                        width_scale = available_width / img_width
                        height_scale = available_height / img_height
                        scale = min(width_scale, height_scale)
                        
                        # Calculate final dimensions
                        final_width = img_width * scale
                        final_height = img_height * scale
                        
                        # Center image on page
                        x = (page_width - final_width) / 2
                        y = (page_height - final_height) / 2
                        
                        # Draw image on PDF
                        pdf_canvas.drawImage(
                            ImageReader(image_path),
                            x, y,
                            width=final_width,
                            height=final_height,
                            preserveAspectRatio=True
                        )
                        
                        # Add new page if not last image
                        if idx < len(image_files) - 1:
                            pdf_canvas.showPage()
                            
                except Exception as e:
                    self.logger.error(f"Error adding image {image_file.get('filename')} to PDF: {str(e)}")
                    continue
            
            # Save PDF
            pdf_canvas.save()
            pdf_content = pdf_buffer.getvalue()
            pdf_buffer.close()
            
            # Write PDF to file
            with open(storage_path, 'wb') as f:
                f.write(pdf_content)
            
            # Create file info for merged PDF
            merged_file_info = {
                'original_url': None,
                'filename': merged_filename,
                'storage_path': storage_path,
                'relative_path': os.path.relpath(storage_path, self.mediaFileCollector.base_storage_path),
                'content_type': 'application/pdf',
                'file_size': len(pdf_content),
                'extension': '.pdf',
                'category': category,
                'from_mobile': mobileNo,
                'message_sid': current_message_sid,
                'download_timestamp': datetime.now().isoformat(),
                'url_hash': None,
                'merged_from': len(image_files),  # Number of images merged
                'is_merged': True
            }
            
            self.logger.info(f"📄 Successfully merged {len(image_files)} images into PDF: {merged_filename} ({len(pdf_content)} bytes)")
            return merged_file_info
            
        except Exception as e:
            self.logger.error(f"Error merging media files to PDF: {str(e)}")
            return None
    
    #endregion webhooks functions
    
    async def statusCallback(self, request:Request):
        # Get the POST data sent by Twilio
        data = await request.form()
        messageSid = data.get('MessageSid')
        messageStatus = data.get('MessageStatus')
        errorCode = data.get('ErrorCode')

        response = MessagingResponse()

        self.logger.debug(f"Received status update for Message SID: {messageSid} with status: {messageStatus} error code: {errorCode}")
        
        return str(response), 200  # Respond with Twilio XML response

    async def dashboard(self, request:Request, guid=''):
        rerfereeDetail = self.refereesByGuid.get(guid)
        name = ''
        if rerfereeDetail:
            name = rerfereeDetail['name']
        return self.templates.TemplateResponse('dashboard.html', guid=guid, name=name)

    async def dashboardLoadDataForReferee(self, guid):
        self.logger.debug(f'dashboardLoadDataForReferee start')
        rerfereeDetail = self.refereesByGuid.get(guid)
        if not rerfereeDetail or not rerfereeDetail.get('refId'):
            data = {}
        else:
            dataFile = self.handleRefereeData.getCollectionSummaryFile(rerfereeDetail['refId'])
            data = jsonHelper.load_from_file(dataFile)
        self.logger.debug(f'dashboardLoadDataForReferee len={len(data["values"])}')
        return JSONResponse(content=data, status_code=200)

    async def dashboardLoadData(self):
        self.logger.debug(f'dashboardLoadData start')
        dataFile = self.handleRefereeData.getCollectionSummaryFile()
        data = jsonHelper.load_from_file(dataFile)
        self.logger.debug(f'dashboardLoadData len={len(data["values"])}')
        return JSONResponse(content=data, status_code=200)

    async def dashboardLoad(self, request:Request):
        import plotly
        import plotly.express as px
        import pandas as pd
        
        self.logger.debug(f'dashboardLoad start')
        dataFile = self.handleRefereeData.getCollectionSummaryFile()
        data1 = jsonHelper.load_from_file(dataFile)
        self.logger.debug(f'dashboardLoad len={len(data1["values"])}')

        # Students data available in a list of list
        students = [['Akash', 34, 'Sydney', 'Australia'],
                    ['Rithika', 30, 'Coimbatore', 'India'],
                    ['Priya', 31, 'Coimbatore', 'India'],
                    ['Sandy', 32, 'Tokyo', 'Japan'],
                    ['Praneeth', 16, 'New York', 'US'],
                    ['Praveen', 17, 'Toronto', 'Canada']]
        
        # Convert list to dataframe and assign column values
        df = pd.DataFrame(students,
                        columns=['Name', 'Age', 'City', 'Country'],
                        index=['a', 'b', 'c', 'd', 'e', 'f'])
        
        # Create Bar chart
        fig = px.bar(df, x='Name', y='Age', color='City', barmode='group')
        
        # Create graphJSON
        testGraphJSON = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        
        # Convert list to dataframe and assign column values
        data = data1['allBars']
        indices = [ bar['label'] for bar in data ]
        barDf = pd.DataFrame(data,
                        columns= ['label', 'section', 'dateSeq', 'gameDay', 'count'],
                        index= indices)
        
        # Create Bar chart
        barFig = px.bar(barDf, x='section', y='count', color='section', barmode='group')
        
        # Create graphJSON
        barChartJSON = json.dumps(barFig, cls=plotly.utils.PlotlyJSONEncoder)
        
        # Use render_template to pass graphJSON to html
        return self.templates.TemplateResponse('bar.html', testGraphJSON=testGraphJSON, barChartJSON=barChartJSON)

    async def dashboardLoad1(self):
        import plotly
        import plotly.express as px
        import pandas as pd

        self.logger.debug(f'dashboardLoad start')
        dataFile = self.handleRefereeData.getCollectionSummaryFile()
        data1 = jsonHelper.load_from_file(dataFile)
        self.logger.debug(f'dashboardLoad len={len(data1["values"])}')

        df1 = pd.DataFrame(data1['multiBarsBySection'])

        # Create a multi-year bar chart using Plotly Express
        fig1 = px.bar(df1, x="labels", y="values", color="name", barmode="group",
                    title="Multi-Year Chart")

        data = {
            "Year": [2018, 2018, 2018, 2019, 2019, 2019, 2020, 2020, 2020],
            "Category": ["A", "B", "C"] * 3,
            "Value": [10, 15, 7, 20, 25, 12, 15, 10, 20]
        }
        df = pd.DataFrame(data)

        # Create a multi-year bar chart using Plotly Express
        fig = px.bar(df, x="Category", y="Value", color="Year", barmode="group",
                    title="Multi-Year Chart")
                
        # Generate the HTML representation of the chart (without a full HTML document)
        chart_html = fig.to_html(full_html=True)

        # Create an HTML template that includes a meta tag for auto-refresh every 30 seconds
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta http-equiv="refresh" content="30">
            <title>Multi-Year Chart</title>
        </head>
        <body>
            <h1>Multi-Year Chart</h1>
            {chart_html}
        </body>
        </html>
        """
        rendered = Template(html_template).render()
        return HTMLResponse(content=rendered)
        
    def calendar(self, request:Request, guid):
        rerfereeDetail = self.refereesByGuid.get(guid)
        name = ''
        if rerfereeDetail:
            name = rerfereeDetail['name']
        firstDay = helpers.localNow().weekday()+1
        title = f'לוח שיבוצים עבור {name}'
        return self.templates.TemplateResponse('calendar.html', guid=guid, name=name, firstDay=firstDay, title=title)

    async def loadCalendar(self, guid):
        self.logger.debug(f'loadCalendar start')
        rerfereeDetail = self.refereesByGuid.get(guid),
        if not rerfereeDetail:
            return {}
        dataFile = self.handleRefereeData.getGamesEventsFile(rerfereeDetail[0]['refId'])
        data = jsonHelper.load_from_file(dataFile, asIs=True)
        self.logger.debug(f'loadCalendar len={len(data)}')

        return JSONResponse(content=data, status_code=200)

    #region LLM integration
    async def test_llm_integration(self, message: str):
        '''Test LLM integration'''
        if hasattr(self, 'llm_enhancer') and self.llm_enhancer:
            try:
                response = await self.llm_enhancer.process_complex_query(message)
                return {
                    'answer': response.answer,
                    'confidence': response.confidence,
                    'sources': response.sources,
                    'action_required': response.action_required
                }
            except Exception as e:
                return {'error': str(e)}
        else:
            return {'error': 'LLM enhancer not available'}

    async def get_llm_stats(self):
        '''Get LLM usage statistics'''
        try:
            # Get recent LLM interactions
            interactions = self.cacheService.getDict(tableName='llm_interactions')
            
            stats = {
                'total_interactions': len(interactions),
                'high_confidence_responses': 0,
                'average_confidence': 0,
                'common_sources': {}
            }
            
            if interactions:
                confidences = []
                sources_count = {}
                
                for interaction in interactions.values():
                    confidence = interaction.get('confidence', 0)
                    confidences.append(confidence)
                    
                    if confidence > 0.8:
                        stats['high_confidence_responses'] += 1
                    
                    for source in interaction.get('sources', []):
                        sources_count[source] = sources_count.get(source, 0) + 1
                
                stats['average_confidence'] = sum(confidences) / len(confidences)
                stats['common_sources'] = dict(sorted(sources_count.items(), 
                                                      key=lambda x: x[1], reverse=True)[:5])
            
            return stats
            
        except Exception as e:
            return {'error': str(e)}
    
    def log_llm_interaction(self, message: str, response):
        """Log LLM interaction to database"""
        try:
            interaction_data = {
                'timestamp': helpers.localNow().isoformat(),
                'message': message,
                'answer': response.answer,
                'confidence': response.confidence,
                'sources': response.sources,
                'action_required': response.action_required,
                'model_used': getattr(response, 'model_id', 'unknown')
            }
            
            table_name = self.config.get('LLM_LOG_TABLE', 'llm_interactions_prod')
            self.cacheService.put(tableName=table_name, data=interaction_data)
            
        except Exception as e:
            self.logger.error(f"Error logging LLM interaction:", e)

    def get_cache_stats(self):
        """Get cache statistics if cache is available"""
        if self.llm_response_cache:
            try:
                return self.llm_response_cache.get_cache_stats()
            except Exception as e:
                self.logger.error(f"Error getting cache stats:", e)
                return None
        return None

    def clear_cache(self):
        """Clear the cache if available"""
        if self.llm_response_cache:
            try:
                success = self.llm_response_cache.clear_all_cache()
                if success:
                    self.logger.info("Cache cleared successfully")
                else:
                    self.logger.warning("Failed to clear cache")
                return success
            except Exception as e:
                self.logger.error(f"Error clearing cache:", e)
                return False
        return False

    def invalidate_cache_entry(self, message: str, referee_detail: dict = None):
        """Invalidate a specific cache entry"""
        if self.llm_response_cache:
            try:
                success = self.llm_response_cache.invalidate_cache(message, referee_detail)
                if success:
                    self.logger.info(f"Cache entry invalidated for message: {message[:50]}...")
                else:
                    self.logger.warning(f"Failed to invalidate cache entry for message: {message[:50]}...")
                return success
            except Exception as e:
                self.logger.error(f"Error invalidating cache entry:", e)
                return False
        return False
    #endregion LLM integration

    #region PWA functions
    async def pwaPair(self, request: Request):
        """Handle pwaPair request from PWA"""
        try:
            method = request.method            
            data = await request.json()
            action = data.get('action')
            client_identifier_header = request.headers.get('X-Client-Identifier')
            session_identifier_header = request.headers.get('X-Session-Identifier')
            self.logger.info(f"pwaPair headers={request.headers} client_identifier_header={client_identifier_header} session_identifier_header={session_identifier_header}")
            clientIdentifier = client_identifier_header
            sessionIdentifier = session_identifier_header
            push_subscription = data.get('pushSubscription')
            userAgent = data.get('userAgent')
            platform = data.get('platform')
            
            self.logger.info(f"checkAuth clientIdentifier={clientIdentifier} sessionIdentifier={sessionIdentifier} push_subscription={push_subscription} userAgent={userAgent} platform={platform}")

            if action != 'הזדהות':
                return JSONResponse(
                    status_code=400, 
                    content={"error": "Invalid action"}
                )
            
            if not clientIdentifier:
                return JSONResponse(
                    status_code=400, 
                    content={"error": "Client unique identifier required"}
                )

            if not sessionIdentifier:
                return JSONResponse(
                    status_code=400, 
                    content={"error": "Session unique identifier required"}
                )

            if False and not push_subscription:
                return JSONResponse(
                    status_code=400, 
                    content={"error": "Push subscription required"}
                )

            queryString = f"pair_pwa_{clientIdentifier}_{sessionIdentifier}"
            self.logger.warning(f"pwaPair queryString={queryString}")
            url = self.messagingService.getWhatsAppUrl(text=queryString)
            return JSONResponse(
                status_code=200,
                content={"url": url}
            )
            
        except Exception as ex:
            self.logger.error(f"pwaPair error: {str(ex)}")
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )

    async def pwaCheckAuth(self, request: Request):
        """Check if a push subscription is authenticated"""
        try:
            clientIdentifier = request.state.client_identifier
            sessionIdentifier = request.state.session_identifier

            self.logger.info(f"checkAuth clientIdentifier={clientIdentifier} sessionIdentifier={sessionIdentifier}")
            if not clientIdentifier or not sessionIdentifier:
                return JSONResponse(
                    status_code=400, 
                    content={"error": "Client unique identifier required"}
                )
            
            # Check if there's a stored push subscription
            value = self.cacheService.getClientIdentifier(clientIdentifier=clientIdentifier)
            if value:
                mobileNo = value.get('mobileNo')
                status = value.get('status') or 'active'
                if sessionIdentifier == value.get('sessionIdentifier') and mobileNo and request.state.mobile_no == mobileNo and status == 'active':
                    response = JSONResponse(content={
                        'authenticated': True
                    })                            
                    return response

        except Exception as ex:
            self.logger.error(f"Check auth error: {str(ex)}")
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )
        
        response = JSONResponse(content={
            'authenticated': False
        })                            
        return response

    async def pwaDashboardLoadData(self, request: Request):
        mobileNo = self.getEffectedMobileNo(request=request)
        return await self.pwaDashboardLoadDataForMobileNo(mobileNo=mobileNo)

    async def pwaDashboardLoadDataForMobileNo(self, mobileNo: str):
        """Get dashboard data for PWA"""
        try:
            #includeArchived = request.query_params.get('includeArchived', False) == 'true'
            #includeRemoved = request.query_params.get('includeRemoved', False) == 'true'
            if mobileNo:
                today = datetime.now().date()
                globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
                tenantKeys = [tenantKey for tenantKey in globalRefereeDetail['activeTenantKeys']]
                pendingGamesCount = 0
                activeAssignedRefereesCount = 0
                activeRefereesCount = 0
                todayGamesCount = 0
                refereeGamesCount = 0
                assignments24HrsCount = 0
                gameApprovals24HrsCount = 0
                gameResultUpdates24HrsCount = 0
                for tenantKey in tenantKeys:
                    tenantReferees = self.refereesByMobile[tenantKey]
                    activeRefereesCount += len(list(filter(lambda x: x.get('status', 'active') == 'active', tenantReferees.values())))
                    pendingGames = self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=None, includeArchived=False, includeRemoved=False, includeCanceled=False, from_date=today, ttlSeconds=60*15)
                    pendingGamesCount += len(set(game.get('gamePk') for game in pendingGames.values() if game['state'] == 'active'))
                    todayGames = list(filter(lambda x: x['date'].date() == today and x['state'] == 'active', pendingGames.values()))
                    todayGamesCount += len(set(game.get('gamePk') for game in todayGames ))
                    assignedRefereesCount = len(set(game.get('refId') for game in pendingGames.values() if game['state'] == 'active'))
                    activeAssignedRefereesCount += assignedRefereesCount
                    assignments24Hrs = self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=None, includeArchived=False, includeRemoved=False, includeCanceled=False, from_created=today-timedelta(days=1), ttlSeconds=60*15)
                    assignments24HrsCount = len(set(tuple((assignment.get('gamePk'), assignment.get('mobileNo')) for assignment in assignments24Hrs.values())))
                    gameApprovals24Hrs = self.cacheService.getRefereeTemplates(tenantKey=tenantKey, mobileNo=None, action='approveGame', status='completed', from_created=today-timedelta(days=1), ttlSeconds=60*15)
                    gameApprovals24HrsCount += len(set(tuple((gameApproval.get('gameId'), gameApproval.get('mobileNo')) for gameApproval in gameApprovals24Hrs.values())))
                    gameResultUpdates24Hrs = self.cacheService.getRefereeTemplates(tenantKey=tenantKey, mobileNo=None, action='postGameUpdate', status='completed', from_created=today-timedelta(days=1), ttlSeconds=60*15)
                    gameResultUpdates24HrsCount += len(set(tuple((gameResultUpdate.get('gameId'), gameResultUpdate.get('mobileNo')) for gameResultUpdate in gameResultUpdates24Hrs.values())))
                data = {
                    "gamesCount": pendingGamesCount,
                    "activeRefereesCount": activeAssignedRefereesCount,
                    "totalRefereesCount": activeRefereesCount,
                    "todayGamesCount": todayGamesCount,
                    "refereeGamesCount": refereeGamesCount,
                    "assignments24HrsCount": assignments24HrsCount,
                    "gameApprovals24HrsCount": gameApprovals24HrsCount,
                    "gameResultUpdates24HrsCount": gameResultUpdates24HrsCount,
                }
                return JSONResponse(content={"success": True, "data": data})

            return JSONResponse(status_code=400, content={"error": "Mobile number not found"})

        except Exception as ex:
            self.logger.error(f"Error getting dashboard data", ex)            
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    def pwa_referee_obj_sync_meta(self, mobileNo: str, tenant_keys: list, obj_type: str) -> dict:
        """Latest automation lastRun / last data lastUpdate for games or reviews (max across tenant keys)."""
        def _sort_key(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val.isoformat(sep='T', timespec='seconds')
            if isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace('Z', '+00:00')).isoformat(sep='T', timespec='seconds')
                except ValueError:
                    return val
            return str(val)

        def _display(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val.strftime('%Y-%m-%d %H:%M')
            if isinstance(val, str):
                try:
                    d = datetime.fromisoformat(val.replace('Z', '+00:00'))
                    return d.strftime('%Y-%m-%d %H:%M')
                except ValueError:
                    return val
            return str(val)

        best_run_key, best_run_disp = None, None
        best_upd_key, best_upd_disp = None, None
        for tk in tenant_keys or []:
            if not tk:
                continue
            run_v = self.cacheService.getCachedKeyVal(tenantKey=tk, mobileNo=mobileNo, propertyName=f'{obj_type}_lastRun')
            upd_v = self.cacheService.getCachedKeyVal(tenantKey=tk, mobileNo=mobileNo, propertyName=f'{obj_type}_lastUpdate')
            rk = _sort_key(run_v)
            if rk and (best_run_key is None or rk > best_run_key):
                best_run_key, best_run_disp = rk, _display(run_v)
            uk = _sort_key(upd_v)
            if uk and (best_upd_key is None or uk > best_upd_key):
                best_upd_key, best_upd_disp = uk, _display(upd_v)
        return {'lastRun': best_run_disp, 'lastUpdate': best_upd_disp}

    async def pwaGetRefereeGames(self, request: Request):
        """Get referee games for PWA"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            includeArchived = request.query_params.get('includeArchived', False) == 'true'
            includeRemoved = request.query_params.get('includeRemoved', False) == 'true'
            includeCanceled = False
            fromDateInput = request.query_params.get('fromDate', None)
            toDateInput = request.query_params.get('toDate', None)
            fromDate = self._parse_query_iso_datetime(fromDateInput) if fromDateInput else None
            toDate = self._parse_query_iso_datetime(toDateInput) if toDateInput else None
        
            games = await self.getRefereeGames(tenantKey=tenantKey, mobileNo=mobileNo, includeArchived=includeArchived, includeRemoved=includeRemoved, includeCanceled=includeCanceled, fromDate=fromDate, toDate=toDate)
            
            if includeCanceled == False:
                games = [game for game in games if 'canceled' not in game or game.get('canceled') == False]
            
            self.logger.info(f"pwaGetRefereeGames mobileNo={mobileNo} includeArchived={includeArchived} includeRemoved={includeRemoved} includeCanceled={includeCanceled} fromDate={fromDate} toDate={toDate} tenantKey={tenantKey} games={len(games)}")

            sync_meta = {'lastRun': None, 'lastUpdate': None}
            if mobileNo:
                referee_detail = self.globalRefereesByMobile[mobileNo]
                meta_keys = [tenantKey] if tenantKey else list(referee_detail.get('tenantKeys', []))
                sync_meta = self.pwa_referee_obj_sync_meta(mobileNo=mobileNo, tenant_keys=meta_keys, obj_type='games')

            convertedValue = jsonHelper.preJsonSetToDynamoDb(games)
            return JSONResponse(
                content={
                    "data": convertedValue,
                    "success": True,
                    "syncMeta": sync_meta,
                },
                headers={"Content-Type": "application/json"}
            )

        except Exception as ex:
            self.logger.error(f"Error getting referee games", ex)            
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error", "detail": str(ex)}
            )

    async def getRefereeGames(self, mobileNo: str, tenantKey: str=None, includeArchived: bool=False, includeRemoved: bool=False, includeCanceled: bool=False, fromDate: datetime=None, toDate: datetime=None):
        """Get referee games for PWA"""
        try:
            self.logger.info(f"getRefereeGames mobileNo={mobileNo} includeArchived={includeArchived} includeRemoved={includeRemoved} includeCanceled={includeCanceled} fromDate={fromDate} toDate={toDate} tenantKey={tenantKey}")
            
            games = []
            
            # Check if there's a stored push subscription
            if mobileNo:
                refereeDetail = self.globalRefereesByMobile[mobileNo]
                tenantKeys:list = []
                if tenantKey:
                    tenantKeys = [tenantKey]
                else:
                    tenantKeys = [tenantKey for tenantKey in refereeDetail.get('tenantKeys', [])]

                games = self.handleRefereeData.getRefereeGames(
                    tenantKey=tenantKeys, 
                    mobileNo=mobileNo, 
                    includeArchived=includeArchived,
                    includeRemoved=includeRemoved,
                    includeCanceled=includeCanceled,
                    from_date=fromDate,
                    to_date=toDate)

            tournaments = {}
            fields = {}
            fullDetailedGames = []
            tenants = self.cacheService.getTenants()
            for game in games.values():
                gamePk = game.get('gamePk')
                try:
                    tenantKey = game['tenantKey']
                    tenant = tenants.get(tenantKey)
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=game)
                    fullDetailedGame = game | (gameDetail or {})
                    fullDetailedGame['state'] = game.get('state')
                    tournamentName = fullDetailedGame.get('tournamentName')
                    tournament = {}
                    if tournamentName:
                        if tournamentName not in tournaments:
                            tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
                            tournaments[tournamentName] = tournament or {}
                        else:
                            tournament = tournaments[tournamentName]
                    fullDetailedGame['tournamentData'] = tournament
                    fieldName = fullDetailedGame.get('field')
                    if fieldName and fieldName not in fields:
                        field = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldName)
                        fields[fieldName] = field or {} 
                    fullDetailedGame['fieldData'] = fields.get(fieldName)
                    fullDetailedGame['icalUrl'] = fullDetailedGame.get('icalUrl') or fullDetailedGame.get('ical_url') or fullDetailedGame.get('calendarUrl') or fullDetailedGame.get('calendar_url')
                    fullDetailedGame['tenantName'] = tenant.get('name')
                    fullDetailedGame['tenantIcon'] = tenant.get('icon')

                    referees:list = fullDetailedGame.get('referees') or list(fullDetailedGame.get('nested', {}).values())
                    for gameReferee in referees:
                        if gameReferee.get('* phone'):
                            gameRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=gameReferee['* phone'])
                            if gameRefereeDetail:
                                gameReferee['address'] = {
                                    'lat': gameRefereeDetail.get('addressDetails', {}).get('coordinates', {}).get('lat'),
                                    'lng': gameRefereeDetail.get('addressDetails', {}).get('coordinates', {}).get('lng')
                                }
                    fullDetailedGames.append(fullDetailedGame)

                except Exception as ex:
                    self.logger.error(f"Error getting game detail {gamePk}", ex, refereeDetail=refereeDetail)

            return fullDetailedGames

        except Exception as ex:
            return []
    
    async def pwaUpdateGameReport(self, request: Request):
        """Update game report for PWA"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            data = await request.json()
            gameId = data.get('gameId')
            data = data.get('data')
            return await self.updateGameReport(mobileNo=mobileNo, gameId=gameId, gameSummary=data)
        except Exception as ex:
            self.logger.error(f"Error updating game report", ex)            
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )

    async def pwaLog(self, request: Request):
        """Receive log messages from PWA client"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            data = await request.json()
            
            clientIdentifier = request.state.client_identifier if hasattr(request.state, 'client_identifier') else None
            logLevel = data.get('level', 'info').upper()
            logMessage = data.get('message', '')
            logType = data.get('type', 'client')
            logData = data.get('data', {})
            
            currentVersion = request.state.current_version if hasattr(request.state, 'current_version') else None
            tokenVersion = request.state.token_version if hasattr(request.state, 'token_version') else None

            # Format log message with context
            context = f"PWA Log:{mobileNo or 'anonymous'} ci:{clientIdentifier} cv:{currentVersion} tv:{tokenVersion}"
            if logType:
                context += f" lt:{logType}"
            
            fullMessage = f"📱 {context}: {logMessage}"
            if logData:
                fullMessage += f" | Data: {json.dumps(logData)}"
            
            # Log based on level
            if logLevel == 'ERROR':
                self.logger.error(fullMessage)
            elif logLevel == 'WARN' or logLevel == 'WARNING':
                self.logger.warning(fullMessage)
            elif logLevel == 'DEBUG':
                self.logger.debug(fullMessage)
            else:  # INFO or default
                self.logger.info(fullMessage)
            
            return JSONResponse(
                status_code=200,
                content={"status": "logged", "message": "Log received successfully"}
            )
        except ClientDisconnect:
            self.logger.info('pwaLog: client disconnected before request body was received')
            raise
        except Exception as ex:
            self.logger.error(f"Error processing PWA log", ex)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

    async def pwaGetRefereeReviews(self, request: Request):
        """Check if a push subscription is authenticated"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            tenantKey = unquote(request.query_params.get('tenantKey', '') or request.query_params.get('tenant', ''))
            empty_meta = {'lastRun': None, 'lastUpdate': None}
            if not mobileNo:
                return JSONResponse(
                    content={
                        "data": {},
                        "success": True,
                        "syncMeta": empty_meta,
                    },
                    headers={"Content-Type": "application/json"}
                )

            refereeDetail = self.globalRefereesByMobile[mobileNo]
            tenantKeys: list = []
            if tenantKey:
                tenantKeys = [tenantKey]
            else:
                tenantKeys = [tenantKey for tenantKey in refereeDetail.get('tenantKeys', [])]

            sync_meta = self.pwa_referee_obj_sync_meta(mobileNo=mobileNo, tenant_keys=tenantKeys, obj_type='reviews')

            reviews = self.handleRefereeData.getRefereeReviews(
                tenantKey=tenantKeys,
                mobileNo=mobileNo,
            )

            for review in reviews.values():
                tkey = review['tenantKey']
                reviewDetail = self.cacheService.getGameDetail(tenantKey=tkey, game=review)
                review |= reviewDetail or {}
                tournamentName = review.get('tournamentName')
                tournament = {}
                if tournamentName:
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tkey, tournamentName=tournamentName)
                review['tournamentData'] = tournament
                fieldName = review.get('field')
                fd = None
                if fieldName:
                    fd = self.cacheService.get_field_by_name(tenantKey=tkey, fieldName=fieldName)
                review['fieldData'] = fd

            convertedValue = jsonHelper.preJsonSetToDynamoDb(reviews)
            return JSONResponse(
                content={
                    "data": convertedValue,
                    "success": True,
                    "syncMeta": sync_meta,
                },
                headers={"Content-Type": "application/json"}
            )
        except Exception as ex:
            self.logger.error(f"Error getting referee details", ex)            
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )

    async def pwaDownloadIcsFile(self, request: Request, gameId: str):
        """Download ics file"""
        try:
            self.logger.info(f"pwaDownloadIcsFile gameId={gameId}")
            mobileNo = request.state.mobile_no
            calendar = await self.createCalendar(mobileNo=mobileNo)
            if calendar is None:
                return JSONResponse(status_code=500, content={"error": "Could not build calendar"})
            return StreamingResponse(
                content=calendar,
                media_type='text/calendar',
                headers={
                    'Content-Disposition': 'attachment; filename="calendar.ics"'
                }
            )
        except Exception as ex:
            self.logger.error(f"Error downloading ics file", ex)

    async def downloadIcsFile(self, request:Request, msgSid):
        """Download ics file"""
        try:
            self.logger.info(f"downloadIcsFile msgSid={msgSid}")
            mobileNo = self.cacheService.getReferenceId(target='msgSid', id=msgSid)
            calendar = await self.createCalendar(mobileNo=mobileNo)
            self.logger.info(f"downloadIcsFile calendar created for mobileNo={mobileNo}")
            if calendar is None:
                return JSONResponse(status_code=500, content={"error": "Could not build calendar"})
            return StreamingResponse(
                content=calendar,
                media_type='text/calendar',
                headers={
                    'Content-Disposition': 'attachment; filename="calendar.ics"'
                }
            )
        except Exception as ex:
            self.logger.error(f"Error downloading ics file", ex)

    async def createCalendar(self, mobileNo: str):
        """Download ics file"""
        try:
            pendingGames = await self.getRefereeGames(mobileNo=mobileNo, includeRemoved=True, fromDate=datetime.now().date())
            calendar = self.handleTournaments.createCalendar(games=pendingGames, mobileNo=mobileNo)
            return calendar
        except Exception as ex:
            self.logger.error(f"Error downloading ics file", ex)

    async def pwaApproveGame(self, request: Request):
        """Check if a push subscription is authenticated"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            data = await request.json()
            gameId = data.get('gameId')
            action = data.get('action')
            if action == 'approve':
                await self.approveGame(mobileNo=mobileNo, gameId=gameId)
            elif action == 'reject':
                await self.declineGame(mobileNo=mobileNo, gameId=gameId)
            return JSONResponse(content={"success": True})
        except Exception as ex:
            self.logger.error(f"Error game approval: {str(ex)}")            
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )

    async def pwaGetFields(self, request: Request, filterText: str = Query(None, alias="filterText")):
        """Fields for PWA map/list; optional tenantKey scopes to one active tenant (e.g. public games)."""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            if mobileNo:
                refereeDetail = self.globalRefereesByMobile[mobileNo]
                tenantKeys = [tenantKey for tenantKey in refereeDetail['activeTenantKeys']]
            else:
                tenantKeys = list(self.activeTenantKeys)

            tenant_key_param = unquote(request.query_params.get('tenantKey', '') or '').strip()
            if tenant_key_param:
                if tenant_key_param not in self.activeTenantKeys:
                    tenantKeys = []
                elif mobileNo:
                    tenantKeys = [tenant_key_param] if tenant_key_param in tenantKeys else []
                else:
                    tenantKeys = [tenant_key_param]
            
            if filterText:
                filterText = unquote(filterText)
            fields = []
            for tenantKey in tenantKeys:
                tenantFields = self.cacheService.search_fields(tenantKey=tenantKey, searchTerm=filterText)
                fields.extend(tenantFields)
            convertedValue = jsonHelper.preJsonSetToDynamoDb(fields)
            return JSONResponse(
                content={
                    "data": convertedValue,
                    "success": True
                },
                headers={"Content-Type": "application/json"}
            )
        except Exception as ex:
            self.logger.error(f"Error getting referee details", ex)            
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )

    async def pwaGetAvailability(self, request: Request):
        """Get referee availability"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            fromDateInput = request.query_params.get('fromDate', None)
            toDateInput = request.query_params.get('toDate', None)
            if fromDateInput:
                fromDate = self._parse_query_iso_datetime(fromDateInput)
                if isinstance(fromDate, datetime):
                    fromDate = fromDate.date()
                if toDateInput:
                    toDate = self._parse_query_iso_datetime(toDateInput)
                    if isinstance(toDate, datetime):
                        toDate = toDate.date()
                else:
                    toDate = fromDate + timedelta(days=6)
            else:
                fromDate = datetime.now().date()
                toDate = datetime.now().date() + timedelta(days=6)

            availability = self.cacheService.getRefereeAvailaiblity(mobileNo=mobileNo, from_date=fromDate + timedelta(days=-7), to_date=toDate)
            if not isinstance(availability, dict):
                availability = {}
            days = (toDate - fromDate).days + 1
            for i in range(-7, days):
                weekDate = fromDate + timedelta(days=i)
                prevWeekDate = weekDate - timedelta(days=7)
                weekDateStr = weekDate.isoformat()
                prevWeekStr = prevWeekDate.isoformat()
                if weekDateStr not in availability:
                    lastWeekDateAvailability = availability.get(prevWeekStr)
                    if lastWeekDateAvailability and lastWeekDateAvailability.get('isConsistent') == 'True':
                        availability[weekDateStr] = {
                            "mobileNo": mobileNo,
                            "date": weekDateStr,
                            "status": lastWeekDateAvailability.get('status'),
                            "fromTime": lastWeekDateAvailability.get('fromTime'),
                            "toTime": lastWeekDateAvailability.get('toTime'),
                            "isConsistent": lastWeekDateAvailability.get('isConsistent'),
                            "notes": lastWeekDateAvailability.get('notes')
                        }
                    else:
                        availability[weekDateStr] = {
                            "mobileNo": mobileNo,
                            "date": weekDateStr,
                            "status": "available",
                            "fromTime": "",
                            "toTime": "",
                            "isConsistent": False,
                            "notes": ""
                        }

            availability = jsonHelper.preJsonSetToDynamoDb(availability)
            return JSONResponse(
                content={
                    "data": availability,
                    "success": True
                },)
        except Exception as ex:
            self.logger.error(f"Error getting referee availability", ex)            
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    async def pwaUpdateRefereeAvailability(self, request: Request):
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            data = await request.json()
            availability = data.get('availability')
            if not isinstance(availability, dict):
                return JSONResponse(status_code=400, content={"error": "availability must be an object"})
            relevantAvailability = {date: availabilityData for date, availabilityData in availability.items() if date >= datetime.now().date().isoformat()}
            self.cacheService.setRefereeAvailaiblity(mobileNo=mobileNo, value=relevantAvailability)
            return JSONResponse(content={"success": True})
        except Exception as ex:
            self.logger.error(f"Error updating referee availability", ex)            
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    async def pwaGetUserDetails(self, request: Request):
        """Get user details (home address, arrival time, commute reminder time, first game reminder time, calendar name)"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
            # Get user properties from cacheService
            originAddress = globalRefereeDetail.get('addressDetails')
            messageAcceptanceLimitation = globalRefereeDetail.get('messageAcceptanceLimitation', True)
            availableFromHour = globalRefereeDetail.get('availableFromHour', '7')
            availableToHour = globalRefereeDetail.get('availableToHour', '21')
            firstGameReminderEnabled = globalRefereeDetail.get('firstGameReminderEnabled', True)
            commuteReminderEnabled = globalRefereeDetail.get('commuteReminderEnabled', True)
            gameLineupsAnnouncedEnabled = globalRefereeDetail.get('gameLineupsAnnouncedEnabled', True)
            firstGameReminderTimeInAdvance = globalRefereeDetail.get('firstGameReminderTimeInAdvance', '24')
            commuteReminderTimeInAdvance = globalRefereeDetail.get('commuteReminderTimeInAdvance', '3')
            timeArrivalInAdvance = globalRefereeDetail.get('timeArrivalInAdvance', '45')
            calendarName = globalRefereeDetail.get('calendarName')
            telegramUsername = globalRefereeDetail.get('telegramUsername', '')
            sendMessagesToTelegram = globalRefereeDetail.get('sendMessagesToTelegram', False)
            tenantRefIds = {}
            for tenantKey in globalRefereeDetail.get('tenantKeys', []):
                tenantReferee = self.cacheService.getReferees(tenantKey=tenantKey, mobileNo=mobileNo)
                if tenantReferee:
                    tenantRefIds[tenantKey] = tenantReferee.get('refId')

            data = {
                "originAddress": originAddress and originAddress.get('address') or "",
                "telegramUsername": telegramUsername,
                "sendMessagesToTelegram": sendMessagesToTelegram,
                "messageAcceptanceLimitation": messageAcceptanceLimitation,
                "availableFromHour": availableFromHour,
                "availableToHour": availableToHour,
                "firstGameReminderEnabled": firstGameReminderEnabled,
                "commuteReminderEnabled": commuteReminderEnabled,
                "gameLineupsAnnouncedEnabled": gameLineupsAnnouncedEnabled,
                "firstGameReminderTimeInAdvance": firstGameReminderTimeInAdvance,
                "commuteReminderTimeInAdvance": commuteReminderTimeInAdvance,
                "timeArrivalInAdvance": timeArrivalInAdvance,
                "calendarName": calendarName or "",
                "tenantRefIds": tenantRefIds
            }

            return JSONResponse(
                content={
                    "success": True,
                    "data": data
                }
            )
            
        except Exception as ex:
            self.logger.error(f"Error getting user details: {str(ex)}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

    def getEffectedMobileNo(self, request: Request):
        if hasattr(request.state, 'mobile_no'):
            mobileNo = request.state.mobile_no
            clientIdentifier = request.state.client_identifier
            if mobileNo == self.adminMobile and request.state.admin_apply_selected_referee:
                    applyMobileNo = request.state.admin_apply_selected_referee
                    self.cacheService.setCachedKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName=f'admin_apply_selected_referee_{clientIdentifier}', value=applyMobileNo)
                    return applyMobileNo
            self.cacheService.setCachedKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName=f'admin_apply_selected_referee_{clientIdentifier}', value=mobileNo)
            return mobileNo
        return None

    async def pwaChangePassword(self, request: Request):
        """Change password for referee in one or more tenants. Password is hashed using bcrypt before saving."""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            data = await request.json()
            passwords = data.get('passwords', {})
            passwordsToChange = {tenantKey: password for tenantKey, password in passwords.items() if password}
            if not passwordsToChange:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "לא הוזנו סיסמאות"}
                )
            
            # Get global referee detail
            globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
            if not globalRefereeDetail:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "משתמש לא נמצא"}
                )
            
            updated_tenants = []
            errors = []
            
            # Process each tenant password
            tenants = self.cacheService.getTenants()
            for tenantKey, password in passwordsToChange.items():
                try:
                    # Validate password length
                    if len(password) < 8:
                        errors.append(f"סיסמה עבור {tenantKey} חייבת להיות לפחות 8 תווים")
                        continue
                    
                    result = self.handleUsers.changeRefereePassword(tenantKey=tenantKey, mobileNo=mobileNo, refPassword=password)                    
                    if not result:
                        self.logger.warning(f"שגיאה בעדכון סיסמה עבור {tenantKey} mobileNo={mobileNo}")
                        errors.append(f"שגיאה בעדכון סיסמה עבור {tenantKey} mobileNo={mobileNo}")
                        continue
                    updated_tenants.append(tenantKey)

                    msgSid = str(uuid.uuid4())[:16]
                    tenant = tenants.get(tenantKey)
                    if tenant and tenant.get('mainAssigner'):
                        mainAsssignerMobileNo = tenant.get('mainAssigner')
                        if mainAsssignerMobileNo:
                            self.cacheService.setRefereeTemplate(tenantKey=tenantKey, mobileNo=mainAsssignerMobileNo, msgSid=msgSid, value={ 'action': 'changePassword', 'data': {'targetMobileNo': mobileNo}, 'status': 'created' })

                except Exception as ex:
                    self.logger.error(f"Error updating password for tenant {tenantKey} mobileNo={mobileNo}:", ex)
                    errors.append(f"שגיאה בעדכון סיסמה עבור {tenantKey}: {str(ex)}")

            if updated_tenants:
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": f"{len(updated_tenants)} סיסמאות עודכנו בהצלחה",
                        "updated_tenants": updated_tenants,
                        "errors": errors if errors else None
                    }
                )
            else:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "; ".join(errors)}
                )
                
        except Exception as ex:
            self.logger.error(f"Error in pwaChangePassword: {ex}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "שגיאה פנימית בשרת"}
            )

    async def pwaUpdateUserDetails(self, request: Request):
        """Update user details (home address, arrival time, commute reminder time, first game reminder time, calendar name)"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
            data = await request.json()
            
            originAddress = data.get('originAddress', '').strip()
            messageAcceptanceLimitation = data.get('messageAcceptanceLimitation', True)
            availableFromHour = data.get('availableFromHour')
            availableToHour = data.get('availableToHour')
            firstGameReminderEnabled = data.get('firstGameReminderEnabled')
            commuteReminderEnabled = data.get('commuteReminderEnabled')
            gameLineupsAnnouncedEnabled = data.get('gameLineupsAnnouncedEnabled')
            firstGameReminderTimeInAdvance = data.get('firstGameReminderTimeInAdvance')
            commuteReminderTimeInAdvance = data.get('commuteReminderTimeInAdvance')
            timeArrivalInAdvance = data.get('timeArrivalInAdvance')
            calendarName = data.get('calendarName', '').strip()
            telegramUsername = data.get('telegramUsername', '').strip()
            sendMessagesToTelegram = data.get('sendMessagesToTelegram')

            # Validate first game reminder time
            if firstGameReminderTimeInAdvance is not None:
                try:
                    firstGameReminderTimeInAdvance = int(firstGameReminderTimeInAdvance)
                    if firstGameReminderTimeInAdvance < 0 or firstGameReminderTimeInAdvance > 168:
                        return JSONResponse(
                            status_code=400,
                            content={"error": "זמן מראש לתזכורת משחק ראשון חייב להיות בין 0 ל-168 שעות"}
                        )
                except (ValueError, TypeError):
                    return JSONResponse(
                        status_code=400,
                        content={"error": "זמן מראש לתזכורת משחק ראשון חייב להיות מספר תקין"}
                    )
            
            # Validate commute reminder time
            if commuteReminderTimeInAdvance is not None:
                try:
                    commuteReminderTimeInAdvance = int(commuteReminderTimeInAdvance)
                    if commuteReminderTimeInAdvance < 0 or commuteReminderTimeInAdvance > 48:
                        return JSONResponse(
                            status_code=400,
                            content={"error": "זמן מראש לתזכורת נסיעה חייב להיות בין 0 ל-48 שעות"}
                        )
                except (ValueError, TypeError):
                    return JSONResponse(
                        status_code=400,
                        content={"error": "זמן מראש לתזכורת נסיעה חייב להיות מספר תקין"}
                    )

            # Validate arrival time
            if timeArrivalInAdvance is not None:
                try:
                    timeArrivalInAdvance = int(timeArrivalInAdvance)
                    if timeArrivalInAdvance < 0 or timeArrivalInAdvance > 180:
                        return JSONResponse(
                            status_code=400,
                            content={"error": "זמן הגעה חייב להיות בין 0 ל-180 דקות"}
                        )
                except (ValueError, TypeError):
                    return JSONResponse(
                        status_code=400,
                        content={"error": "זמן הגעה חייב להיות מספר תקין"}
                    )
            
            # Save properties using cacheService
            if originAddress:
                currentOriginAddress = globalRefereeDetail.get('addressDetails')

                if not currentOriginAddress or currentOriginAddress.get('address') != originAddress:
                    addressDetails = self.handleUsers.generateRefereeAddress(originAddress)
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='addressDetails',
                        value=addressDetails
                    )

            updateMessageAcceptanceLimitation = False
            if messageAcceptanceLimitation is not None:
                currentMessageAcceptanceLimitation = globalRefereeDetail.get('messageAcceptanceLimitation')
                if currentMessageAcceptanceLimitation is None or currentMessageAcceptanceLimitation != messageAcceptanceLimitation:
                    updateMessageAcceptanceLimitation = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='messageAcceptanceLimitation',
                        value=messageAcceptanceLimitation
                    )

            updateAvailableFromHour = False
            if availableFromHour is not None:
                currentAvailableFromHour = globalRefereeDetail.get('availableFromHour')
                if currentAvailableFromHour is None or currentAvailableFromHour != availableFromHour:
                    updateAvailableFromHour = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='availableFromHour',
                        value=availableFromHour
                    )

            updateAvailableToHour = False
            if availableToHour is not None:
                currentAvailableToHour = globalRefereeDetail.get('availableToHour')
                if currentAvailableToHour is None or currentAvailableToHour != availableToHour:
                    updateAvailableToHour = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='availableToHour',
                        value=availableToHour
                    )                        

            updateFirstGameReminderEnabled = False
            if firstGameReminderEnabled is not None:
                currentFirstGameReminderEnabled = globalRefereeDetail.get('firstGameReminderEnabled')
                if currentFirstGameReminderEnabled is None or currentFirstGameReminderEnabled != firstGameReminderEnabled:
                    updateFirstGameReminderEnabled = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='firstGameReminderEnabled',
                        value=firstGameReminderEnabled
                    )                        

            updateCommuteReminderEnabled = False
            if commuteReminderEnabled is not None:
                currentCommuteReminderEnabled = globalRefereeDetail.get('commuteReminderEnabled')
                if currentCommuteReminderEnabled is None or currentCommuteReminderEnabled != commuteReminderEnabled:
                    updateCommuteReminderEnabled = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='commuteReminderEnabled',
                        value=commuteReminderEnabled
                    )                        

            updateGameLineupsAnnouncedEnabled = False
            if gameLineupsAnnouncedEnabled is not None:
                currentGameLineupsAnnouncedEnabled = globalRefereeDetail.get('gameLineupsAnnouncedEnabled')
                if currentGameLineupsAnnouncedEnabled is None or currentGameLineupsAnnouncedEnabled != gameLineupsAnnouncedEnabled:
                    updateGameLineupsAnnouncedEnabled = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='gameLineupsAnnouncedEnabled',
                        value=gameLineupsAnnouncedEnabled
                    )                        

            if commuteReminderTimeInAdvance is not None:
                currentCommuteReminderTimeInAdvance = globalRefereeDetail.get('commuteReminderTimeInAdvance')
                if currentCommuteReminderTimeInAdvance is None or int(currentCommuteReminderTimeInAdvance) != commuteReminderTimeInAdvance:
                    updateCommuteReminderTimeInAdvance = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='commuteReminderTimeInAdvance',
                        value=commuteReminderTimeInAdvance
                    )

            updateFirstGameReminderTimeInAdvance = False
            if firstGameReminderTimeInAdvance is not None:
                currentFirstGameReminderTimeInAdvance = globalRefereeDetail.get('firstGameReminderTimeInAdvance')

                if currentFirstGameReminderTimeInAdvance is None or int(currentFirstGameReminderTimeInAdvance) != firstGameReminderTimeInAdvance:
                    updateFirstGameReminderTimeInAdvance = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='firstGameReminderTimeInAdvance',
                        value=firstGameReminderTimeInAdvance
                    )
            
            updateCommuteReminderTimeInAdvance = False
            if commuteReminderTimeInAdvance is not None:
                currentCommuteReminderTimeInAdvance = globalRefereeDetail.get('commuteReminderTimeInAdvance')

                if currentCommuteReminderTimeInAdvance is None or int(currentCommuteReminderTimeInAdvance) != commuteReminderTimeInAdvance:
                    updateCommuteReminderTimeInAdvance = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='commuteReminderTimeInAdvance',
                        value=commuteReminderTimeInAdvance
                    )
            
            updateTimeArrivalInAdvance = False
            if timeArrivalInAdvance is not None:
                currentTimeArrivalInAdvance = globalRefereeDetail.get('timeArrivalInAdvance')

                if currentTimeArrivalInAdvance is None or int(currentTimeArrivalInAdvance) != timeArrivalInAdvance:
                    updateTimeArrivalInAdvance = True
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='timeArrivalInAdvance',
                        value=timeArrivalInAdvance
                    )

            # Update calendar name if provided
            if calendarName is not None:
                currentCalendarName = globalRefereeDetail.get('calendarName')
                if currentCalendarName != calendarName:
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='calendarName',
                        value=calendarName
                    )

            # Update send messages to Telegram preference if provided
            if sendMessagesToTelegram is not None:
                currentSendMessagesToTelegram = globalRefereeDetail.get('sendMessagesToTelegram', False)
                if currentSendMessagesToTelegram != sendMessagesToTelegram:
                    self.cacheService.setRefereeProperty(
                        tenantKey='GLOBAL',
                        mobileNo=mobileNo,
                        propertyName='sendMessagesToTelegram',
                        value=bool(sendMessagesToTelegram)
                    )

            pendingGames = await self.getRefereeGames(mobileNo=mobileNo)
            for game in pendingGames:
                if firstGameReminderEnabled:
                    if updateFirstGameReminderTimeInAdvance:
                        gameNotifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='tournamentGames', id=game['gamePk'], notificationType='gameFirstReminder', status='created')
                        for notification in gameNotifications.values():
                            notification['reminderInHrs'] = firstGameReminderTimeInAdvance
                            self.cacheService.setNotification(tenantKey=game['tenantKey'], target='tournamentGames', id=game['gamePk'], notificationType='gameFirstReminder', to=None, timestamp=notification['timestamp'], value=notification)
                else:
                    gameNotifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='tournamentGames', id=game['gamePk'], notificationType='gameFirstReminder', status='created')
                    for notification in gameNotifications.values():
                        notification['status'] = 'deleted'
                        self.cacheService.setNotification(tenantKey=game['tenantKey'], target='tournamentGames', id=game['gamePk'], notificationType='gameFirstReminder', to=None, timestamp=notification['timestamp'], value=notification)

                if commuteReminderEnabled:
                    if updateCommuteReminderTimeInAdvance:
                        gameNotifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='refereeLastReminder', status='created', to=mobileNo)
                        for notification in gameNotifications.values():
                            notification['reminderInHrs'] = commuteReminderTimeInAdvance
                            self.cacheService.setNotification(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='refereeLastReminder', to=mobileNo, timestamp=notification['timestamp'], value=notification)
                else:
                    gameNotifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='refereeLastReminder', status='created', to=mobileNo)
                    for notification in gameNotifications.values():
                        notification['status'] = 'deleted'
                        self.cacheService.setNotification(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='refereeLastReminder', to=mobileNo, timestamp=notification['timestamp'], value=notification)

                if not updateGameLineupsAnnouncedEnabled:
                    gameNotifications = self.cacheService.getNotifications(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='gameLineupsAnnounced', status='created', to=mobileNo)
                    for notification in gameNotifications.values():
                        notification['status'] = 'deleted'
                        self.cacheService.setNotification(tenantKey=game['tenantKey'], target='refereeGames', id=game['gamePk'], notificationType='gameLineupsAnnounced', to=mobileNo, timestamp=notification['timestamp'], value=notification)

            self.logger.info(f"User details updated for mobile {mobileNo}: address={bool(originAddress)}, arrivalTime={timeArrivalInAdvance} minutes, commuteReminder={commuteReminderTimeInAdvance} hours, firstGameReminder={firstGameReminderTimeInAdvance} hours")
            
            return JSONResponse(
                content={
                    "success": True,
                    "message": "פרטי משתמש עודכנו בהצלחה"
                }
            )
            
        except Exception as ex:
            self.logger.error(f"Error updating user details: {str(ex)}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

    async def pwaGetRules(self, request: Request):
        """Get rules"""
        pass

    def _parse_message_datetime(self, datetime_str):
        """Parse message datetime string to datetime object"""
        if not datetime_str or not isinstance(datetime_str, str):
            return helpers.localNow()
        
        try:
            # Try ISO format first
            if 'Z' in datetime_str:
                datetime_str = datetime_str.replace('Z', '+00:00')
            return datetime.fromisoformat(datetime_str)
        except:
            try:
                # Try common formats
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                    try:
                        return datetime.strptime(datetime_str, fmt)
                    except:
                        continue
            except:
                pass
        
        return helpers.localNow()

    def _pwa_message_source(self, msg_data: dict) -> str:
        raw = msg_data.get('source')
        if raw is None or raw == '':
            return 'unknown'
        return str(raw).strip()

    def _pwa_message_provider_from_source(self, source: str) -> str:
        s = (source or '').lower()
        if s in ('meta', 'greenapi', 'twillio', 'twilio', 'manychat'):
            return 'whatsapp'
        if s == 'push':
            return 'push'
        if s == 'telegram':
            return 'telegram'
        return 'unknown'

    async def pwaGetMessages(self, request: Request):
        """Get messages for PWA"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            if not mobileNo:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Bad request", "success": False}
                )
            
            # Get filter parameters
            direction_param = request.query_params.get('direction', 'both')
            provider_param = request.query_params.get('provider', 'all')
            source_param = request.query_params.get('source', 'all')
            fromDateInput = request.query_params.get('fromDate', None)
            toDateInput = request.query_params.get('toDate', None)
            fromDate = self._parse_query_iso_datetime(fromDateInput) if fromDateInput else None
            toDate = self._parse_query_iso_datetime(toDateInput) if toDateInput else None
            
            all_messages = []
            
            # Get messages based on direction filter
            if direction_param == 'both' or direction_param == 'from':
                from_messages = self.cacheService.getRefereeMessages(mobileNo=mobileNo, direction='FROM', from_created=fromDate, to_created=toDate)
                if from_messages and isinstance(from_messages, dict):
                    for msgSid, msg_data in from_messages.items():
                        source = self._pwa_message_source(msg_data)
                        provider = self._pwa_message_provider_from_source(source)

                        # Get mobile number - for FROM messages, it's the sender
                        msg_mobile = None
                        if isinstance(msg_data.get('to'), list) and len(msg_data.get('to', [])) > 0:
                            msg_mobile = msg_data.get('to')[0]
                        elif isinstance(msg_data.get('to'), str):
                            msg_mobile = msg_data.get('to')
                        else:
                            msg_mobile = mobileNo
                        
                        all_messages.append({
                            'direction': 'from',
                            'source': source,
                            'provider': provider,
                            'created': msg_data.get('created'),
                            'mobileNo': msg_mobile,
                            'message': msg_data.get('message') or msg_data.get('messageBody') or msg_data.get('buttonId') or '',
                            'msgSid': msgSid
                        })
    
            if direction_param == 'both' or direction_param == 'to':
                to_messages = self.cacheService.getRefereeMessages(mobileNo=mobileNo, direction='TO', from_created=fromDate, to_created=toDate)
                if to_messages and isinstance(to_messages, dict):
                    for msgSid, msg_data in to_messages.items():
                        source = self._pwa_message_source(msg_data)
                        provider = self._pwa_message_provider_from_source(source)

                        message = msg_data.get('message') or msg_data.get('messageBody') or msg_data.get('buttonId') or msg_data.get('text', {}).get('body', '') or msg_data.get('interactive', {}).get('body', {}).get('text', '') or ''
                        if 'template' in msg_data:
                            templateName = msg_data.get('template').get('name')
                            parameters = [ component.get('parameters') for component in msg_data['template'].get('components', []) if component.get('type') == 'body' ][0]
                            parameterText = '\n'.join([ parameter.get('text') for parameter in parameters ])
                            message = f"{templateName}\n{parameterText}"

                        all_messages.append({
                            'direction': 'to',
                            'source': source,
                            'provider': provider,
                            'created': msg_data.get('created'),
                            'mobileNo': mobileNo,
                            'message': message,
                            'msgSid': msgSid
                        })
    
            # Filter by provider / source
            if provider_param != 'all':
                all_messages = [msg for msg in all_messages if msg['provider'].lower() == provider_param.lower()]
            if source_param != 'all':
                all_messages = [msg for msg in all_messages if msg.get('source', '').lower() == source_param.lower()]
            
            # Sort by datetime (newest first)
            all_messages.sort(key=lambda x: x.get('created', ''), reverse=True)  
            allMessagesJson = jsonHelper.preJsonSetToDynamoDb(all_messages)

            self.logger.info(f"pwaGetMessages mobileNo={mobileNo} direction={direction_param} provider={provider_param} source={source_param} fromDate={fromDate} toDate={toDate} messages={len(all_messages)}")
            
            return JSONResponse(
                content={
                    "data": allMessagesJson,
                    "success": True
                },
                headers={"Content-Type": "application/json"}
            )
            
        except Exception as ex:
            self.logger.error(f"Error getting messages", ex)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "detail": str(ex), "success": False}
            )

    async def pwaGetDocuments(self, request: Request):
        """Get documents"""
        try:
            mobileNo = self.getEffectedMobileNo(request=request)
            if mobileNo:
                refereeDetail = self.globalRefereesByMobile[mobileNo]
                tenantKeys = [tenantKey for tenantKey in refereeDetail['activeTenantKeys']]
            else:
                tenantKeys = list(self.activeTenantKeys)
            self.logger.info(f"pwaGetDocuments mobileNo={mobileNo}, tenantKeys={tenantKeys}")
            documents = {}
            for tenantKey in tenantKeys:
                tenantDocuments = self.cacheService.getDocuments(tenantKey=tenantKey)
                documents = { **documents, **tenantDocuments }
                
            return JSONResponse(
                content={
                    "data": list(jsonHelper.preJsonSetToDynamoDb(documents).values()),
                    "success": True
                })
        except Exception as ex:
            self.logger.error(f"Error getting documents", ex)            
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    async def pwaUnpair(self, request: Request):
        """Handle pwaUnpair request from PWA"""
        try:
            clientIdentifier = request.state.client_identifier
            sessionIdentifier = request.state.session_identifier

            await self.pwaUpdateClientIdentifiers(clientIdentifier=clientIdentifier, sessionIdentifier=sessionIdentifier, remove=True)

            return JSONResponse(
                content={"message": "pwaUnpair completed successfully"}
            )
            
        except Exception as e:
            self.logger.error(f"pwaUnpair error: {str(e)}")
            return JSONResponse(
                status_code=500, 
                content={"error": "Internal server error"}
            )

    async def pwaSetPushSubscription(self, request: Request):
        """Handle POST request to set push subscription and save to database"""
        try:
            clientIdentifier = request.state.client_identifier
            sessionIdentifier = request.state.session_identifier
            mobile_no = request.state.mobile_no

            data = await request.json()
            if isinstance(data, str):
                self.logger.warning(f"pwaSetPushSubscription data is a string: {data}")
                return JSONResponse(
                    status_code=400,
                    content={"error": "Invalid data"}
                )
            
            push_subscription = data.get('pushSubscription') or 'MISSING_PUSH_SUBSCRIPTION'
            userAgent = data.get('userAgent')
            platform = data.get('platform')
            validate = data.get('validate', False)  # Optional validation flag from frontend
            
            # Validate subscription only if explicitly requested (not on every save)
            # Best practice: Validate lazily when sending notifications, not on every save
            # This avoids unnecessary test notifications and reduces server load
            validation_result = None
            if validate and push_subscription and isinstance(push_subscription, dict) and push_subscription != 'EXPIRED_PUSH_SUBSCRIPTION' and push_subscription != 'MISSING_PUSH_SUBSCRIPTION':
                try:
                    validation_result = self.messagingService.validatePushSubscription(pushSubscription=push_subscription)
                    
                    if validation_result.get('expired'):
                        # Subscription is expired, mark it as such
                        self.logger.warning(f"Push subscription expired for mobile {mobile_no}, marking as expired")
                        push_subscription = 'EXPIRED_PUSH_SUBSCRIPTION'
                    elif not validation_result.get('valid'):
                        # Subscription is invalid but not expired
                        self.logger.warning(f"Push subscription invalid for mobile {mobile_no}: {validation_result.get('error')}")
                        # Still save it, but log the warning
                    else:
                        self.logger.info(f"Push subscription validated successfully for mobile {mobile_no}")
                except Exception as validation_error:
                    # If validation fails (e.g., network error), still save the subscription
                    # The expiration will be detected when we try to send notifications (lazy validation)
                    self.logger.warning(f"Could not validate push subscription for mobile {mobile_no}: {validation_error}")
            
            # Save to database using the existing database client
            await self.pwaUpdateClientIdentifiers(clientIdentifier=clientIdentifier, sessionIdentifier=sessionIdentifier, pushSubscription=push_subscription, mobileNo=mobile_no, userAgent=userAgent, platform=platform)
            
            self.logger.info(f"Push subscription updated saved for mobile {mobile_no}")
            
            return JSONResponse(
                content={
                    "message": "Push subscription updated successfully",
                    "validated": validation_result.get('valid', False) if 'validation_result' in locals() and validation_result else None,
                    "expired": validation_result.get('expired', False) if 'validation_result' in locals() and validation_result else None
                }
            )
            
        except Exception as ex:
            self.logger.error(f"Error setting push subscription: {str(ex)}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

    async def flushPositionUpdate(self, clientIdentifier:str, data:dict):
        try:
            client_data = self.cacheService.getClientIdentifier(clientIdentifier=clientIdentifier)
            mobile_no = client_data.get('mobileNo') if client_data else None
            
            if not mobile_no:
                self.logger.warning(f"Could not find mobile number for client {clientIdentifier}")
                return
            
            # Extract position data
            position = data.get('position', {})
            distance = data.get('distance', 0)  # Distance in meters
            timeFromLastCall = data.get('timeFromLastCall', 0)  # Time in milliseconds
            
            # Get current timestamp
            timestamp = position.get('timestamp')
            
            # Create position update record
            position_update = {
                'mobileNo': mobile_no,
                'clientIdentifier': clientIdentifier,
                'timestamp': timestamp, # Original GPS timestamp
                'latitude': position.get('latitude'),
                'longitude': position.get('longitude'),
                'accuracy': position.get('accuracy'),
                'distance': distance,  # Distance accumulated since tracking started
                'timeFromLastCall': timeFromLastCall,  # Time since last position update
            }
            
            # Save to database using cacheService
            self.cacheService.setPositionUpdate(mobileNo=mobile_no, timestamp=timestamp, value=position_update)
            
            self.logger.debug(f"Position update saved via WebSocket for mobile {mobile_no}: distance={distance}m, timeSinceLastCall={timeFromLastCall}ms")
            
            return timestamp
        except Exception as ex:
            self.logger.error(f"Error saving position update via WebSocket: {str(ex)}")

    async def handlePositionUpdateViaWebSocket(self, client_identifier: str, message: dict):
        """Handle position update received via WebSocket"""
        try:
            timestamp = await self.flushPositionUpdate(clientIdentifier=client_identifier, data=message)
            
        except Exception as ex:
            self.logger.error(f"Error saving position update via WebSocket: {str(ex)}")

    async def pwaPositionUpdate(self, request: Request):
        """Handle POST request to save position update from distance tracker (HTTP fallback)"""
        try:
            clientIdentifier = request.state.client_identifier
            data = await request.json()
            timestamp = await self.flushPositionUpdate(clientIdentifier=clientIdentifier, data=data)
            
            return JSONResponse(
                content={
                    "message": "Position update saved successfully",
                    "timestamp": timestamp
                }
            )
            
        except Exception as ex:
            self.logger.error(f"Error saving position update: {str(ex)}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )

    async def pwaSpeedTrackingData(self, request: Request):
        """Handle POST request to save speed tracking data (timestamp, distance, speed, accuracy)"""
        try:
            mobileNo = request.state.mobile_no
            data = await request.json()
            
            # Extract tracking summary data
            startTime = data.get('startTime')
            endTime = data.get('endTime')
            duration = data.get('duration', 0)
            totalDistance = data.get('totalDistance', 0)
            totalDataPoints = data.get('totalDataPoints', 0)
            trackingData = data.get('data', [])
            
            # Format timestamps as strings (convert from milliseconds to datetime)
            startTimeFormatted = datetime.fromtimestamp(startTime / 1000).strftime('%Y-%m-%d %H:%M:%S') if startTime else None
            endTimeFormatted = datetime.fromtimestamp(endTime / 1000).strftime('%Y-%m-%d %H:%M:%S') if endTime else None
            
            # Create tracking record with metadata
            trackingRecord = {
                'mobileNo': mobileNo,
                'startTime': startTimeFormatted,
                'endTime': endTimeFormatted,
                'duration': duration,  # milliseconds
                'totalDistance': totalDistance,  # meters
                'totalDataPoints': totalDataPoints,
                'data': trackingData  # Array of {timestamp, latitude, longitude, accuracy, speed, distance, distanceIncrement}
            }
            
            # Use endTime as the timestamp for the record
            timestamp = endTime or int(time.time() * 1000)  # Convert to milliseconds if needed
            timestamp_str = str(timestamp)
            
            trackingId = f"{mobileNo}_{timestamp_str}"
            storagePath = os.path.join(self.trackingDataStoragePath, f'speedTrackingData_{trackingId}.json')
            jsonHelper.save_to_file(trackingRecord, storagePath)
            self.logger.info(f"Speed tracking data saved for mobile {mobileNo}: {totalDataPoints} data points, {totalDistance}m total distance, {duration}ms duration, trackingId: {trackingId}")
            
            return JSONResponse(
                content={
                    "success": True,
                    "message": "Speed tracking data saved successfully",
                    "trackingId": trackingId,
                    "totalDataPoints": totalDataPoints,
                    "totalDistance": totalDistance,
                    "duration": duration
                }
            )
            
        except Exception as ex:
            self.logger.error(f"Error saving speed tracking data: {str(ex)}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "Internal server error"}
            )

    async def pwaUpdateClientIdentifiers(self, clientIdentifier, sessionIdentifier, pushSubscription=None, mobileNo=None, userAgent=None, platform=None, status=None, remove=False):
        try:
            if not clientIdentifier or not sessionIdentifier:
                return
            
            value = self.cacheService.getClientIdentifier(clientIdentifier=clientIdentifier)
            existingValue = helpers.safeClone(value)
            if value:
                mobileNo = mobileNo or value.get('mobileNo')
                status = status or value.get('status')
                pushSubscription = pushSubscription or value.get('pushSubscription')
                userAgent = userAgent or value.get('userAgent')
                platform = platform or value.get('platform')
            
            anyChange = False
            if mobileNo:
                current_client_identifiers:list = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='clientIdentifiers') or []
                if remove:
                    if clientIdentifier in current_client_identifiers:
                        current_client_identifiers.remove(clientIdentifier)
                        anyChange = True
                elif clientIdentifier not in current_client_identifiers:
                    current_client_identifiers.append(clientIdentifier)
                    anyChange = True

                if anyChange:
                    self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=current_client_identifiers, propertyName='clientIdentifiers')

            if remove:
                self.cacheService.setClientIdentifier(clientIdentifier=clientIdentifier, sessionIdentifier='XX', pushSubscription='XX', mobileNo='XX')
            else:
                if existingValue:
                    if existingValue.get('sessionIdentifier') != sessionIdentifier:
                        anyChange = True
                    if existingValue.get('mobileNo') != mobileNo:
                        anyChange = True
                    elif existingValue.get('pushSubscription') != pushSubscription:
                        anyChange = True
                    elif existingValue.get('userAgent') != userAgent:
                        anyChange = True
                    elif existingValue.get('platform') != platform:
                        anyChange = True
                if not existingValue or anyChange:
                    self.cacheService.setClientIdentifier(
                        clientIdentifier=clientIdentifier, 
                        sessionIdentifier=sessionIdentifier,
                        pushSubscription=pushSubscription, 
                        mobileNo=mobileNo, 
                        userAgent=userAgent, 
                        platform=platform,
                        status=status)
                    self.logger.info(f"Client identifier updated: {clientIdentifier}")

        except Exception as e:
            None

    async def generateJwtTokens(self, request: Request, clientIdentifier: str, mobileNo: str):
        globalRefereeDetail = self.globalRefereesByMobile.get(mobileNo)
        if not globalRefereeDetail:
            return None
        jwtTokenService = request.app.state.jwt_token_service
        tenantRefIds, userValidSections = jwtTokenService.getUserSectionsAndTenantRefIds(globalRefereeDetail=globalRefereeDetail)
        
        # Get app version from request header
        app_version = request.headers.get('X-App-Version') if request else None
        
        # Create token pair using the new system
        token_data = {
            'clientIdentifier': clientIdentifier,
            'refName': globalRefereeDetail and globalRefereeDetail.get('name') or hasattr(request.state, 'ref_name') and request.state.ref_name or '',
            'role': globalRefereeDetail and globalRefereeDetail.get('role') or hasattr(request.state, 'role') and request.state.role or 'User',
            'mobileNo': globalRefereeDetail and globalRefereeDetail.get('mobileNo') or hasattr(request.state, 'mobile_no') and request.state.mobile_no or '',
            'allowedSections': userValidSections or [],
            'tenantRefIds': tenantRefIds or {}
        }
        
        new_tokens = jwtTokenService.create_token_pair(token_data, app_version=app_version)
        return new_tokens

    def getPendingJwtToken(self, client_identifier: str) -> str:
        """Get pending JWT token for a client identifier"""
        # This could be stored in Redis, database, or memory
        # For now, let's use a simple in-memory approach
        pending_jwt_tokens = getattr(self, '_pending_jwt_tokens', {})
        return pending_jwt_tokens.get(client_identifier)
    
    def setPendingJwtToken(self, client_identifier: str, jwt_token: str):
        """Set pending JWT token for a client identifier"""
        if not hasattr(self, '_pending_jwt_tokens'):
            self._pending_jwt_tokens = {}
        self._pending_jwt_tokens[client_identifier] = jwt_token
    
    def clearPendingJwtToken(self, client_identifier: str):
        """Clear pending JWT token for a client identifier"""
        if hasattr(self, '_pending_jwt_tokens'):
            self._pending_jwt_tokens.pop(client_identifier, None)

    async def handleLoginApproval(self, mobileNo, verification_code):
        """Handle login approval button click - pair mobile number with push identifier"""
        try:
            # Extract the stored push subscription endpoint
            temp_key = f"login_pending_key"
            saved_verification_code = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName=temp_key)
            if not saved_verification_code or saved_verification_code != verification_code:
                return "שגיאה: לא נמצאה בקשת הזדהות תלויה"
            
            # Clean up the temporary storage
            self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, value=None, propertyName=temp_key)
            
            # Send confirmation message
            await self.messagingService.sendMessage(
                to=mobileNo,
                message="✅ הזדהות אושרה בהצלחה! כעת תוכל לקבל התראות מהמערכת."
            )
            
            return "הזדהות אושרה בהצלחה"
            
        except Exception as e:
            self.logger.error(f"Error handling login approval: {str(e)}")
            return "שגיאה באישור ההזדהות"

    async def pwaWebsocketEndpoint(self, websocket: WebSocket):
        """WebSocket endpoint on server for JWT token delivery"""
        try:
            client_identifier: str = websocket.path_params.get('client_identifier')
            # Connect the WebSocket
            await self.websocketManager.connect(websocket, client_identifier)
            
            # Check if we have a pending JWT token for this client
            pending_jwt_data = self.getPendingJwtToken(client_identifier=client_identifier)
            if pending_jwt_data:
                # Handle both old string format and new dict format for backward compatibility
                if isinstance(pending_jwt_data, dict):
                    # New format: token pair
                    self.logger.warning(f"In pwaWebsocketEndpoint#1 sending jwt token pair to {client_identifier} {pending_jwt_data}")
                    await self.websocketManager.send_jwt_token(
                        client_identifier=client_identifier, 
                        access_token=pending_jwt_data['access_token'], 
                        refresh_token=pending_jwt_data['refresh_token'],
                        access_expires_in=pending_jwt_data.get('access_expires_in', 86400),
                        refresh_expires_in=pending_jwt_data.get('refresh_expires_in', 2592000)
                    )
                else:
                    # Old format: single token string
                    self.logger.warning(f"In pwaWebsocketEndpoint#2 sending jwt token string to {client_identifier} {pending_jwt_data}")
                    await self.websocketManager.send_jwt_token(client_identifier=client_identifier, access_token=pending_jwt_data)
                self.clearPendingJwtToken(client_identifier)
            
            # Keep connection alive and handle disconnection
            while True:
                # Wait for any message from client (ping, etc.)
                data = await websocket.receive_text()
                # Handle client messages if needed
                
                try:
                    message = json.loads(data)
                    if message.get("type") == "log":
                        self.logger.info(f"📨 CLIENT:{client_identifier}: Received log:{message.get('logType')} {message.get('log')}")
                    elif message.get("type") == "position_update":
                        # Handle position update from distance tracker
                        await self.handlePositionUpdateViaWebSocket(client_identifier=client_identifier, message=message)
                    elif message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    else:
                        self.logger.info(f"📨 Received websocket message: {message}")
                except json.JSONDecodeError:
                    pass
                                    
        except WebSocketDisconnect as ex:
            self.logger.info(f"WebSocket disconnected on server for client {client_identifier}: {ex}")
        except Exception as ex:
            self.logger.error(f"WebSocket error on server for {client_identifier}:", ex)
            if websocket.client_state.CONNECTED:
                await websocket.close()
        finally:
            self.logger.info(f"WebSocket finally disconnected on server for client {client_identifier}")
            await self.websocketManager.disconnect(websocket)

    # Add this method to your class
    async def wsTestEndpoint(self, websocket: WebSocket):
        """Simple test WebSocket endpoint"""
        try:
            await websocket.accept()
            self.logger.info("✅ Test WebSocket connection accepted")
            
            # Send a welcome message
            await websocket.send_json({
                "type": "welcome",
                "message": "Test WebSocket connection established!",
                "timestamp": "2024-01-01T00:00:00Z"
            })
            
            # Keep connection alive and handle messages
            try:
                while True:
                    # Wait for any message from client
                    data = await websocket.receive_text()
                    self.logger.info(f"📨 Received message: {data}")
                    
                    try:
                        message = json.loads(data)
                        if message.get("type") == "ping":
                            await websocket.send_json({"type": "pong", "message": "Pong response"})
                            self.logger.info("🏓 Ping received, sent pong")
                        else:
                            # Echo back the message
                            await websocket.send_json({
                                "type": "echo",
                                "original_message": message,
                                "timestamp": "2024-01-01T00:00:00Z"
                            })
                            self.logger.info("🔄 Echoed message back")
                            
                    except json.JSONDecodeError:
                        # Send back the raw text
                        await websocket.send_json({
                            "type": "echo",
                            "original_message": data,
                            "timestamp": "2024-01-01T00:00:00Z"
                        })
                        self.logger.info("🔄 Echoed raw text back")
                        
            except WebSocketDisconnect:
                self.logger.info("🔌 Test WebSocket disconnected")
                
        except Exception as e:
            self.logger.error(f"❌ Test WebSocket error:", e)
            if websocket.client_state.CONNECTED:
                await websocket.close()

    # Add WebSocket health check
    async def pwaWebsocketStatus(self, request: Request):
        """Get WebSocket connection status"""
        if hasattr(self, 'websocket_manager'):
            connected_clients = self.websocketManager.get_connected_clients()
            return {
                "connected_clients": len(connected_clients),
                "client_identifiers": list(connected_clients)
            }
        else:
            return {"error": "WebSocket manager on server not available"}

    async def sendTestPushNotification(self, request: Request):
        """Send push notification"""
        try:
            message = request.query_params.get('message')
            sentPushMsgIds = self.messagingService.sendPushNotification(to=self.adminMobile, title='test title', body=message or 'test body', url='https://pws-dev.refereex.com:8443/refportal-pwa.html#games', critical=False)
            return JSONResponse(content={"message": "Push test notification sent successfully"})
        except Exception as ex:
            self.logger.error(f"Error sending push notification: {str(ex)}")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})

    async def pwaBroadcastRefreshPush(self, request: Request):
        """
        After deploy: notify all PWA clients to refresh (Web Push). Protected by X-PWA-Broadcast-Key
        matching config PWA_BROADCAST_REFRESH_SECRET.
        Body JSON optional: { "title", "body", "maxAgeDays" }.
        """
        try:
            secret = ConfigManager.get_config_value(self.config, 'PWA_BROADCAST_REFRESH_SECRET')
            if not secret:
                return JSONResponse(
                    status_code=503,
                    content={
                        'success': False,
                        'error': 'PWA_BROADCAST_REFRESH_SECRET is not configured',
                    },
                )
            hdr = request.headers.get('X-PWA-Broadcast-Key') or request.headers.get('x-pwa-broadcast-key')
            if hdr != secret:
                return JSONResponse(
                    status_code=403,
                    content={'success': False, 'error': 'Forbidden'},
                )
            body = {}
            try:
                body = await request.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            title = body.get('title')
            body_text = body.get('body')
            try:
                max_age_days = int(body.get('maxAgeDays', 365))
            except (TypeError, ValueError):
                max_age_days = 365
            stats = self.messagingService.broadcastPwaRefreshPushNotification(
                title=title,
                body=body_text,
                max_age_days=max_age_days,
            )
            return JSONResponse(content={'success': True, **stats})
        except Exception as ex:
            self.logger.error(f'pwaBroadcastRefreshPush: {ex}', exc_info=True)
            return JSONResponse(
                status_code=500,
                content={'success': False, 'error': str(ex)},
            )

    async def pwaSendReportEmail(self, request: Request):
        """Send game report email with PDF attachment"""
        try:
            recipients = [
                { 'name': 'openreport', 'email': 'openreports@refereex.com' },
                { 'name': 'Guy Shachar', 'email': 'guyshachar.acc@gmail.com' }
            ]
            
            # Get request body
            body = await request.json()
            
            # Validate required fields
            required_fields = ['gameId', 'gameTitle', 'gameDate', 'gameTime', 'league', 'field', 'categories', 'details', 'reporter']
            for field in required_fields:
                if field not in body:
                    return JSONResponse(
                        status_code=400, 
                        content={"error": f"Missing required field: {field}"}
                    )
            
            # Add timestamp
            body['reportDatetime'] = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            
            # Generate PDF and HTML
            self.logger.info(f"Generating PDF for game report: {body.get('gameId')}")
            pdf_content = self.reportsService.generate_pdf(body)
            html_content = self.reportsService.generate_html(body)
            
            # Create attachments array with both PDF and HTML
            attachment = [
                {
                    'name': f"open-game-report-{body.get('gameId')}-{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    'content': base64.b64encode(pdf_content).decode('utf-8')
                }
            ]

            # Send email
            self.logger.info(f"Sending report email for game: {body.get('gameId')}")

            messageId = await self.messagingService.sendEmail(
                    recipients=recipients,
                    subject=f"דו״ח תיקון משחק - {body.get('gameTitle')}",
                    body=html_content,
                    attachment=attachment,
                    fromName=body.get('reporter')
            )

            if messageId:
                return JSONResponse(content={
                    "success": True,
                    "message": f"Report email sent successfully {messageId}",
                })
            else:
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": 'Failed to send email'
                    }
                )
                
        except Exception as ex:
            self.logger.error(f"Error sending report email: {str(ex)}")
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Internal server error",
                    "details": str(ex)
                }
            )
    async def pwaGetPublicLeagueTables(self, request: Request):
        """Return league tables for all (or one) tenant/league — no auth required."""
        try:
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            leagueName = unquote(request.query_params.get('leagueName', ''))
            sectionFilter = unquote(request.query_params.get('section', ''))

            tenantKeys = [tenantKey] if tenantKey else list(self.activeTenantKeys)
            result = []

            for tk in tenantKeys:
                tournaments = self.cacheService.getTournaments(tenantKey=tk) or {}
                for name, tournament in tournaments.items():
                    if tournament.get('tournament') != 'league':
                        continue
                    if leagueName and name != leagueName:
                        continue
                    if sectionFilter and tournament.get('section', '') != sectionFilter:
                        continue

                    table = self.cacheService.getLeagueTables(tenantKey=tk, tournamentName=name)
                    if not table:
                        continue

                    teams = jsonHelper.load_from_json(table.get('value'))
                    table_rows = [
                        {'team': team, **stats}
                        for team, stats in teams.items()
                        if isinstance(stats, dict)
                    ]
                    try:
                        table_rows.sort(key=lambda x: int(str(x.get('מיקום', '99')).replace('*', '').strip() or '99'))
                    except Exception:
                        pass

                    result.append({
                        'tenantKey': tk,
                        'leagueName': name,
                        'displayName': tournament.get('text', name),
                        'section': tournament.get('section', ''),
                        'table': table_rows,
                    })

            return JSONResponse(
                content={"data": jsonHelper.preJsonSetToDynamoDb(result), "success": True},
                headers={"Content-Type": "application/json"},
            )
        except Exception as ex:
            self.logger.error(f"Error in pwaGetPublicLeagueTables", ex)
            return JSONResponse(status_code=500, content={"error": str(ex)})

    def _parse_pwa_public_games_request(self, request: Request) -> dict:
        tenantKey = unquote(request.query_params.get('tenantKey', ''))
        leagueName = unquote(request.query_params.get('leagueName', ''))
        sectionFilter = unquote(request.query_params.get('section', ''))
        refereeFilter = unquote(request.query_params.get('referee', ''))
        refereeMobileFilter = unquote(request.query_params.get('refereeMobile', '')).strip()
        fieldFilter = unquote(request.query_params.get('field', '')).strip()
        fromDateInput = request.query_params.get('fromDate', None)
        toDateInput = request.query_params.get('toDate', None)
        fromDate = datetime.fromisoformat(unquote(fromDateInput)) if fromDateInput else None
        toDate = datetime.fromisoformat(unquote(toDateInput)) if toDateInput else None
        pairedMobileNo = None
        authHeader = request.headers.get('Authorization', '')
        if authHeader.startswith('Bearer '):
            try:
                token = authHeader.split(' ')[1]
                jwtTokenService = request.app.state.jwt_token_service
                payload = jwtTokenService.verify_token(token=token, request=request, check_version=False)
                pairedMobileNo = payload.get('mobileNo')
            except Exception:
                pass
        return {
            'tenantKey': tenantKey,
            'leagueName': leagueName,
            'sectionFilter': sectionFilter,
            'refereeFilter': refereeFilter,
            'refereeMobileFilter': refereeMobileFilter,
            'fieldFilter': fieldFilter,
            'fromDate': fromDate,
            'toDate': toDate,
            'pairedMobileNo': pairedMobileNo,
        }

    async def pwaGetPublicGames(self, request: Request):
        """Return public games list — referee details only for started games or the paired user's own games."""
        try:
            params = self._parse_pwa_public_games_request(request)
            allGames = await self.getPublicGames(**params)
            if isinstance(allGames, list):
                return JSONResponse(
                    content={"data": jsonHelper.preJsonSetToDynamoDb(allGames), "success": True},
                    headers={"Content-Type": "application/json"},
                )
        except Exception as ex:
            self.logger.error(f"Error in pwaGetPublicGames", ex)
            return JSONResponse(status_code=500, content={"error": str(ex)})

    async def pwaGetPublicGamesStream(self, request: Request):
        """Stream public games with per-tournament progress (SSE)."""
        try:
            params = self._parse_pwa_public_games_request(request)

            def event_stream():
                yield ": connected\n\n"
                for event in self._iter_public_games_events(**params):
                    payload = jsonHelper.preJsonSetToDynamoDb(event)
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                event_stream(),
                media_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'Connection': 'keep-alive',
                    'X-Accel-Buffering': 'no',
                },
            )
        except Exception as ex:
            self.logger.error(f"Error in pwaGetPublicGamesStream", ex)
            return JSONResponse(status_code=500, content={"error": str(ex)})

    def _iter_public_games_events(
        self,
        tenantKey: str,
        leagueName: str,
        sectionFilter: str,
        refereeFilter: str,
        refereeMobileFilter: str,
        fieldFilter: str,
        fromDate: datetime,
        toDate: datetime,
        pairedMobileNo: str = None,
    ):
        """Yield progress/chunk/done events while loading public games tournament-by-tournament."""
        tenantKeys = [tenantKey] if tenantKey else list(self.activeTenantKeys)
        tenants = self.cacheService.getTenants()
        now = datetime.now(_tz.utc)

        def _norm_phone_pub(p):
            return ''.join(c for c in str(p or '') if c.isdigit())

        def _ref_phone_pub(ref):
            if not isinstance(ref, dict):
                return ''
            return str(ref.get('* phone') or ref.get('phone') or ref.get('mobileNo') or '').strip()

        def _ref_name_pub(ref):
            if not isinstance(ref, dict):
                return ''
            return str(ref.get('* name') or ref.get('name') or '').strip()

        def _public_referee_display_label(ref):
            name = _ref_name_pub(ref)
            phone_digits = _norm_phone_pub(_ref_phone_pub(ref))
            tail = phone_digits[-3:] if len(phone_digits) >= 3 else phone_digits
            if name:
                return f"{name} ({tail})" if tail else name
            return phone_digits or ''

        def _referee_matches_referee_param(ref, rf: str) -> bool:
            if not (rf or '').strip():
                return True
            rf = str(rf).strip()
            rf_lower = rf.lower()
            label = _public_referee_display_label(ref)
            if rf_lower in label.lower():
                return True
            if rf_lower in _ref_name_pub(ref).lower():
                return True
            q_digits = _norm_phone_pub(rf)
            if q_digits:
                pd = _norm_phone_pub(_ref_phone_pub(ref))
                if pd and (pd == q_digits or pd.endswith(q_digits)):
                    return True
            return False

        def _raw_referees_for_public_filter(fg: dict):
            arr = fg.get('referees')
            if isinstance(arr, list) and len(arr) > 0:
                return arr
            nested = fg.get('nested') or {}
            if isinstance(nested, dict) and nested:
                return list(nested.values())
            return []

        referee_mobile_digits = _norm_phone_pub(refereeMobileFilter) if refereeMobileFilter else ''

        ref_games_by_tournament = None
        if refereeMobileFilter:
            try:
                _rg = self.handleRefereeData.getRefereeGames(
                    tenantKey=tenantKeys,
                    mobileNo=refereeMobileFilter,
                    includeArchived=True,
                    includeRemoved=False,
                    includeCanceled=False,
                    from_date=fromDate,
                    to_date=toDate,
                )
            except Exception:
                _rg = None
            if _rg is not None:
                ref_games_by_tournament = {}
                for g in _rg.values():
                    tkg, tnm, gpk = g.get('tenantKey'), g.get('tournamentName'), g.get('gamePk')
                    if tkg in tenantKeys and tnm and gpk is not None and str(gpk) != '':
                        ref_games_by_tournament.setdefault((tkg, tnm), set()).add(str(gpk))
                if not ref_games_by_tournament:
                    yield {'type': 'progress', 'current': 0, 'total': 0}
                    yield {'type': 'done', 'totalGames': 0}
                    return

        candidates = []
        for tk in tenantKeys:
            tournaments = self.cacheService.getTournaments(tenantKey=tk) or {}
            tenant = tenants.get(tk, {})
            for tName, tournament in tournaments.items():
                if leagueName and tName != leagueName:
                    continue
                if sectionFilter and tournament.get('section', '') != sectionFilter:
                    continue
                if ref_games_by_tournament is not None and (tk, tName) not in ref_games_by_tournament:
                    continue
                candidates.append((tk, tName, tournament, tenant))

        total = len(candidates)
        yield {'type': 'progress', 'current': 0, 'total': total, 'phase': 'prepare'}

        total_games = 0
        for idx, (tk, tName, tournament, tenant) in enumerate(candidates, 1):
            yield {
                'type': 'progress',
                'current': idx - 1,
                'total': total,
                'tournamentName': tName,
                'phase': 'index',
            }
            tournament_games = []
            _allowed_pks = ref_games_by_tournament.get((tk, tName)) if ref_games_by_tournament is not None else None
            index_matched_pks = None
            if _allowed_pks is None:
                index_matched_pks = self.cacheService.queryTournamentGamesIndex(
                    tenantKey=tk,
                    tournamentName=tName,
                    sectionFilter=sectionFilter,
                    fromDate=fromDate,
                    toDate=toDate,
                    fieldFilter=fieldFilter,
                    refereeFilter=refereeFilter if not refereeMobileFilter else None,
                    now=now,
                )
            yield {
                'type': 'progress',
                'current': idx - 1,
                'total': total,
                'tournamentName': tName,
                'phase': 'games',
            }
            if _allowed_pks is not None:
                _game_items = self.cacheService.getTournamentGames(
                    tenantKey=tk, tournamentName=tName, gamePk=_allowed_pks
                ) or {}
            elif index_matched_pks is not None:
                if not index_matched_pks:
                    yield {'type': 'progress', 'current': idx, 'total': total, 'tournamentName': tName}
                    continue
                _game_items = self.cacheService.getTournamentGames(
                    tenantKey=tk, tournamentName=tName, gamePk=index_matched_pks
                ) or {}
            else:
                _game_items = self.cacheService.getTournamentGames(tenantKey=tk, tournamentName=tName) or {}

            for gamePk, gameDetail in _game_items.items():
                if not gameDetail:
                    self.logger.error(f"Game detail not found for gamePk={gamePk} tournamentName={tName} tenantKey={tk}")
                    continue

                if index_matched_pks is None and (_allowed_pks is None):
                    gameDate = gameDetail.get('date') or gameDetail.get('gameDate') or gameDetail.get('scheduledDate')
                    if fromDate or toDate:
                        if not gameDate:
                            continue
                        try:
                            gdt = datetime.fromisoformat(str(gameDate)).replace(tzinfo=_tz.utc)
                            if fromDate and gdt < fromDate.replace(tzinfo=_tz.utc):
                                continue
                            if toDate and gdt > toDate.replace(tzinfo=_tz.utc):
                                continue
                        except Exception:
                            continue

                fullGame = gameDetail | {}
                gameDateTime = fullGame.get('scheduledDate') or fullGame.get('dateTime') or fullGame.get('date')
                gameHasStarted = False
                if gameDateTime:
                    try:
                        gdt = datetime.fromisoformat(str(gameDateTime))
                        if gdt.tzinfo is None:
                            gdt = gdt.replace(tzinfo=_tz.utc)
                        gameHasStarted = gdt <= now
                    except Exception:
                        pass

                if index_matched_pks is None and fieldFilter:
                    fd = fullGame.get('fieldData')
                    fd = fd if isinstance(fd, dict) else {}
                    addr_raw = fd.get('addressDetails')
                    addr = addr_raw if isinstance(addr_raw, dict) else {}
                    field_blob = ' '.join(
                        str(x)
                        for x in (
                            fullGame.get('field'),
                            fullGame.get('fieldName'),
                            fd.get('name'),
                            addr.get('address'),
                        )
                        if x
                    )
                    if fieldFilter.lower() not in field_blob.lower():
                        continue

                rawReferees = _raw_referees_for_public_filter(fullGame)
                userIsInGame = pairedMobileNo and any(
                    _norm_phone_pub(_ref_phone_pub(ref)) == _norm_phone_pub(pairedMobileNo)
                    or _norm_phone_pub(_ref_phone_pub(ref)).endswith(_norm_phone_pub(pairedMobileNo))
                    for ref in rawReferees
                ) or False
                if gameHasStarted or userIsInGame:
                    fullGame['referees'] = [
                        {'name': _ref_name_pub(ref), 'role': ref.get('role') or ref.get('* role', '')}
                        for ref in rawReferees
                    ]
                else:
                    fullGame['referees'] = []

                if refereeMobileFilter:
                    if not (gameHasStarted or userIsInGame) or referee_mobile_digits and not any(
                        _norm_phone_pub(_ref_phone_pub(ref)) == referee_mobile_digits
                        or _norm_phone_pub(_ref_phone_pub(ref)).endswith(f':{referee_mobile_digits}')
                        for ref in rawReferees
                    ):
                        continue
                elif refereeFilter:
                    if not (gameHasStarted or userIsInGame) or not any(
                        _referee_matches_referee_param(ref, refereeFilter) for ref in rawReferees
                    ):
                        continue

                fullGame.pop('nested', None)
                fullGame['tenantName'] = tenant.get('name', '')
                fullGame['tenantIcon'] = tenant.get('icon', '')
                fullGame['leagueName'] = tName
                fullGame['leagueSection'] = tournament.get('section', '')
                tournament_games.append(fullGame)

            if tournament_games:
                tournament_games.sort(
                    key=lambda g: str(g.get('date') or g.get('gameDate') or g.get('scheduledDate') or ''),
                    reverse=True,
                )
                total_games += len(tournament_games)
                yield {'type': 'chunk', 'games': tournament_games}
            yield {'type': 'progress', 'current': idx, 'total': total, 'tournamentName': tName}

        yield {'type': 'done', 'totalGames': total_games}

    async def getPublicGames(self, tenantKey: str, leagueName: str, sectionFilter: str, refereeFilter: str, refereeMobileFilter: str, fieldFilter: str, fromDate: datetime, toDate: datetime, pairedMobileNo: str = None):
        """Return public games list — referee details only for started games or the paired user's own games."""
        allGames = []
        for event in self._iter_public_games_events(
            tenantKey=tenantKey,
            leagueName=leagueName,
            sectionFilter=sectionFilter,
            refereeFilter=refereeFilter,
            refereeMobileFilter=refereeMobileFilter,
            fieldFilter=fieldFilter,
            fromDate=fromDate,
            toDate=toDate,
            pairedMobileNo=pairedMobileNo,
        ):
            if event.get('type') == 'chunk':
                allGames.extend(event.get('games') or [])
        allGames.sort(key=lambda g: str(g.get('date') or g.get('gameDate') or g.get('scheduledDate') or ''), reverse=True)
        return allGames

    async def pwaGetPublicTablesFilters(self, request: Request):
        """Section/league options for public league tables — no full table payloads."""
        try:
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            tenantKeys = [tenantKey] if tenantKey else list(self.activeTenantKeys)
            sections_set = set()
            leagues = []
            seen_league = set()
            for tk in tenantKeys:
                tournaments = self.cacheService.getTournaments(tenantKey=tk, forceReload=True) or {}
                for name, tournament in tournaments.items():
                    if tournament.get('tournament') != 'league':
                        continue
                    sec = tournament.get('section', '') or ''
                    sections_set.add(sec)
                    lk = (name, sec)
                    if lk in seen_league:
                        continue
                    seen_league.add(lk)
                    leagues.append({
                        'leagueName': name,
                        'section': sec,
                        'displayName': tournament.get('text', name),
                    })
            sections = sorted(s for s in sections_set if s) or sorted(sections_set)
            leagues.sort(key=lambda x: (x.get('section') or '', x.get('leagueName') or ''))
            payload = {'sections': sections, 'leagues': leagues}
            return JSONResponse(
                content={"data": jsonHelper.preJsonSetToDynamoDb(payload), "success": True},
                headers={"Content-Type": "application/json"},
            )
        except Exception as ex:
            self.logger.error(f"Error in pwaGetPublicTablesFilters", ex)
            return JSONResponse(status_code=500, content={"error": str(ex)})

    async def pwaGetPublicGamesFilters(self, request: Request):
        """Section/league from tournaments; fields from fields table; referees from tenant referee properties."""
        try:
            tenantKey = unquote(request.query_params.get('tenantKey', ''))
            tenantKeys = [tenantKey] if tenantKey else list(self.activeTenantKeys)
            sections_set = set()
            leagues = []
            seen_league = set()
            field_strings = set()
            referees_out = []
            seen_mobile = set()

            for tk in tenantKeys:
                tournaments = self.cacheService.getTournaments(tenantKey=tk, forceReload=True) or {}
                for tName, tournament in tournaments.items():
                    sec = tournament.get('section', '') or ''
                    sections_set.add(sec)
                    lk = (tName, sec)
                    if lk not in seen_league:
                        seen_league.add(lk)
                        leagues.append({'leagueName': tName, 'section': sec})

                fields_map = self.cacheService.getFields(tenantKey=tk) or {}
                for fk, field in fields_map.items():
                    if not isinstance(field, dict):
                        continue
                    label = None
                    for x in (field.get('title'), field.get('fieldName'), fk):
                        if x and str(x).strip():
                            label = str(x).strip()
                            break
                    if not label:
                        ad = field.get('addressDetails')
                        if isinstance(ad, dict) and ad.get('address'):
                            label = str(ad.get('address')).strip()
                    if label:
                        field_strings.add(label)

                tenant_referees_by_mobile = self.refereesByMobile.get(tk) or {}
                for mobile_no, rd in tenant_referees_by_mobile.items():
                    if not isinstance(rd, dict):
                        continue
                    if False and rd.get('status', 'active') not in  ('active', 'draft'):
                        continue
                    m = str(mobile_no).strip()
                    if not m or m in seen_mobile:
                        continue
                    seen_mobile.add(m)
                    referees_out.append({
                        'mobileNo': m,
                        'refId': str(rd.get('refId') or rd.get('ref_id') or ''),
                        'name': str(rd.get('name') or '').strip(),
                    })

            sections = sorted(s for s in sections_set if s) or sorted(sections_set)
            leagues.sort(key=lambda x: (x.get('section') or '', x.get('leagueName') or ''))
            fields = sorted(field_strings, key=lambda x: x.lower())
            referees_out.sort(key=lambda r: (r.get('name') or '').lower() + '@@@' + r.get('mobileNo', ''))
            data = {
                'sections': sections,
                'leagues': leagues,
                'fields': fields,
                'referees': referees_out,
            }
            return JSONResponse(
                content={"data": jsonHelper.preJsonSetToDynamoDb(data), "success": True},
                headers={"Content-Type": "application/json"},
            )
        except Exception as ex:
            self.logger.error(f"Error in pwaGetPublicGamesFilters", ex)
            return JSONResponse(status_code=500, content={"error": str(ex)})

    #endregion PWA functions

    #region Media file functions
    async def getMediaFiles(self, request: Request):
        """Get media files for a specific mobile number or message SID"""
        try:
            mobileNo = request.query_params.get('mobile_no')
            message_sid = request.query_params.get('message_sid')
            
            if mobileNo:
                media_files = self.cacheService.getMediaFilesByMobile(mobile_no=mobileNo)
            elif message_sid:
                media_files = self.cacheService.getMediaFilesByMessageSid(message_sid=message_sid)
            else:
                return JSONResponse(status_code=400, content={"error": "Either mobile_no or message_sid parameter is required"})
            
            return JSONResponse(content={"media_files": media_files})
        except Exception as ex:
            self.logger.error(f"Error getting media files: {str(ex)}")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})
    
    async def getMediaFile(self, request: Request, file_id: str):
        """Get specific media file information"""
        try:
            file_info = self.mediaFileCollector.get_media_file_info(file_id=file_id)
            if not file_info:
                return JSONResponse(status_code=404, content={"error": "Media file not found"})
            
            return JSONResponse(content={"file_info": file_info})
        except Exception as ex:
            self.logger.error(f"Error getting media file info: {str(ex)}")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})
    
    async def downloadMediaFile(self, request: Request, file_id: str):
        """Download a media file"""
        try:
            file_info = self.mediaFileCollector.get_media_file_info(file_id=file_id)
            if not file_info:
                return JSONResponse(status_code=404, content={"error": "Media file not found"})
            
            # Get full path
            full_path = os.path.join(self.mediaFileCollector.base_storage_path, file_info['storage_path'])
            
            if not os.path.exists(full_path):
                return JSONResponse(status_code=404, content={"error": "Media file not found on disk"})
            
            # Return file
            return FileResponse(
                path=full_path,
                filename=file_info['filename'],
                media_type=file_info['content_type']
            )
        except Exception as ex:
            self.logger.error(f"Error downloading media file: {str(ex)}")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})
    
    async def cleanupOldMediaFiles(self, request: Request):
        """Clean up old media files"""
        try:
            days_old = int(request.query_params.get('days_old', 30))
            cleaned_count = self.mediaFileCollector.cleanup_old_files(days_old=days_old)
            
            return JSONResponse(content={
                "message": f"Cleaned up {cleaned_count} old media files",
                "cleaned_count": cleaned_count,
                "days_old": days_old
            })
        except Exception as ex:
            self.logger.error(f"Error cleaning up old media files: {str(ex)}")
            return JSONResponse(status_code=500, content={"error": "Internal server error"})
    #endregion Media file functions

if __name__ == '__main__':
    useApi = eval(os.getenv('useApi', 'False'))    
    from shared.appContainer import AppContainer
    container = AppContainer.getAppContainer()
    cacheService:CacheService = container.cache_service()
    impl:RefPortalImplementationApi = container.ref_portal_implementation()
    
    #refereesDetails = cacheService.getRefereesNoCache()
    globalRefereeDetail = impl.globalRefereesByMobile.get('+972547144766')
    tenantReferees = impl.refereesByMobile['IL#handball#2025-26']
    exit(0)
    repliedAnswer = asyncio.run(impl.declineGame(mobileNo='+972547799979' , gameId='ABBCD123', msgSid='currentMessageSid'))
    
    #_2FA_PortalCode_RequestDatetime = cacheService.getCachedKeyVal(tenantKey='IL#football#2025-26', mobileNo='+972547799979', propertyName='2FA_PortalCode_RequestDatetime')

    #games = asyncio.run(impl.getPublicGames(tenantKey='IL#football#2025-26', leagueName='', sectionFilter='', refereeFilter='', refereeMobileFilter='224606', fieldFilter='', fromDate=datetime.now().date() - timedelta(days=1), toDate=datetime.now().date() + timedelta(days=1), pairedMobileNo=None))
    exit(0)
    messagingService:MessagingService = container.messaging_service()

    mobileNo = '+972547799979'
    pendingGames = asyncio.run(impl.getRefereeGames(mobileNo=mobileNo, includeRemoved=False, includeArchived=False, fromDate=datetime.now().date()))
    for game in pendingGames:
        print(f'{game.get('gamePk')} {game.get('gameTitle')} {game.get('gameDateTime')}')
        asyncio.run(messagingService.sendNewGameNotification(refereeGame=game, title='*שיבוץ חדש*', refId=game.get('refId'), toMobile=mobileNo, toName=game.get('name'), sendAt=None, skipPushNotification=True))
    exit(0)

    clientIdentifiers = cacheService.getClientIdentifier(clientIdentifier=None, from_date=helpers.localNow() - timedelta(days=14))
    mobileNos = list({clientIdentifier.get('mobileNo') for clientIdentifier in clientIdentifiers.values() if clientIdentifier.get('mobileNo')})
    uniqueMobileNos = list(set(mobileNos))
    referees = cacheService.getRefereesNoCache()
    handballReferees = referees.get('IL#handball#2025-26')
    activeReferees = [ referee for referee in handballReferees.values() if referee.get('status') == 'active' ]
    nonActiveReferees = [ referee for referee in handballReferees.values() if referee.get('status') != 'active' ]
    exit(0)
    for mobileNo in mobileNos:
        tenantRefereeDetail = cacheService.getReferees(tenantKey='IL#handball#2025-26', mobileNo=mobileNo)
        if not tenantRefereeDetail:
            continue
        print(f'{mobileNo} {tenantRefereeDetail.get('status')}')
        if tenantRefereeDetail.get('status', '') != 'active':
            asyncio.run(impl.activateByMobileNo(mobileNo=mobileNo))
    
    tenantReferees = impl.refereesByMobile.get('IL#handball#2025-26')
    activeReferees = [ referee for referee in tenantReferees.values() if referee.get('status') == 'active' ]
    for mobileNo, referee in tenantReferees.items():
        if referee.get('status') == 'pending':
            asyncio.run(impl.activateByMobileNo(mobileNo=mobileNo))
            print(f'{mobileNo} {referee.get('status')}')
    exit(0)

    asyncio.run(impl.sendNewJoiner(mobileNo='+972547799979'))
    globalRefereeDetail = impl.globalRefereesByMobile.get('+972559194567')

    calendar = asyncio.run(impl.createCalendar(mobileNo='+972547799979'))
    exit(0)
    #asyncio.run(impl.downloadMediaFilesAndStore(fromMobileNo='+972547799979', current_message_sid='123', tag='test', media_files=[{'media_id': '31323615290586389'}]))
    #result = asyncio.run(impl.getGameUpdateTemplate(mobileNo='+972547799979', gameId='ec701a15'))
    asyncio.run(impl.pwaDashboardLoadDataForMobileNo(mobileNo='+972547799979'))
    pass
    asyncio.run(impl.getGameUpdateTemplate(mobileNo='+972547799979', gameId='e67d471d'))
    summary = open('/Users/guyshachar/Projects/Python/PythonProjects/apps/refPortal/tmp/summary.txt', 'r').read()
    asyncio.run(impl.postGameUpdate(mobileNo='+972547799979', msgSid='ec701a15', summary=summary))
    #result = asyncio.run(impl.getRefereeGames(mobileNo='+972506440002', fromDate=datetime.now().date()))
    exit(0)

    # Create config for testing
    config = {
        'docsServiceUrlBase': os.getenv('docsServiceUrlBase', ''),
        'LLM': {
            'enabled': os.getenv('LLM_ENABLED', 'False') == 'True',
            'use_cache': True,
            'use_redis_cache': os.getenv('LLM_USE_REDIS_CACHE', 'True') == 'True',
            'cache_ttl_seconds': int(os.getenv('LLM_CACHE_TTL_SECONDS', '3600')),
            'cache_max_size': int(os.getenv('LLM_CACHE_MAX_SIZE', '10000'))
        }
    }
    
    pass
    """
    flow
        #1 send askToJoin_+972
        #2 IncomingWebhook - When message received the message
                Create user using MobileNo as LoginId
                Send template message to referee with JoiningConfirmation_+972...  (open 24hrs window)
        #3 IncomingWebhook - When message received send Registration message with link to registration page
        #4 When registration submitted - Create user and delete mobile user
    """