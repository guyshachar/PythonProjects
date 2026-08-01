import os
import uuid
import sys
from pathlib import Path
import firebase_admin
import boto3
import urllib.parse
import logging
import requests
import asyncio
import json
import re
from typing import Callable, Any, Dict, Tuple, Optional, TYPE_CHECKING
import functools
from datetime import datetime, timedelta
import time
from zoneinfo import ZoneInfo
from pywebpush import webpush, WebPushException
from fastapi import Request
from urllib.parse import urlparse
from firebase_admin import credentials, messaging
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.messaging.twilioClient import TwilioClient, readWA
from shared.messaging.greenApiClient import GreenApiClient
from shared.messaging.manyChatClient import ManychatClient
from shared.messaging.metaClient import MetaClient
from shared.messaging.telegramClient import TelegramClient
from shared.messaging.mqttClient import MqttClient
from shared.messaging.apnsClient import ApnsClient
from shared.db import CacheService
from shared.db.repositories import TenantRepository
from shared.logger import Logger
from shared.configManager import ConfigManager
from shared.db.models.enums import NotificationTypeKey

if TYPE_CHECKING:
    from shared.commonHelper import CommonHelper

@staticmethod
def _adjustMobileNo(mobileNo):
    if not mobileNo:
        return None
    mobileNo = _clean_number_string(mobileNo)
    mobileNo = mobileNo.replace(' ','').replace('-','').replace('+','').replace('‑','')
    if len(mobileNo) == 10:
        mobileNo = f'972{mobileNo[1:]}'
    elif len(mobileNo) == 9:
        mobileNo = f'972{mobileNo}'
    return f'+{mobileNo}'

@staticmethod
def _clean_number_string(s):
    # Remove any invisible characters
    s = re.sub(r'[\u202a\u202c\u200e\u200f\xa0\u2066\u2067\u2068\u2069]', '', s)
    # Replace non-standard hyphens with normal ones
    s = s.replace('‑', '-')  # Unicode hyphen to normal hyphen
    # Remove hyphens/spaces if you want pure digits
    s = re.sub(r'[^0-9]', '', s)
    return s

class MessagingService():
    """WhatsApp / messaging orchestration (Twilio, Meta, Green API, etc.)."""

    META_DELIVERY_MAX_META_ATTEMPTS = 3

    def __init__(
            self,
            logger:Logger,
            cacheService:CacheService,
            commonHelper:'CommonHelper',
            referees_data:tuple,
            activeClient:str,
            twilioClient:TwilioClient=None,
            greenApiClient:GreenApiClient=None,
            metaClient:MetaClient=None,
            manychatClient:ManychatClient=None,
            telegramClient:TelegramClient=None,
            useMessageTemplates:bool=False,
            messageTemplates:dict=None,
            config:dict=None,
            tenantRepository:TenantRepository=None):

        self.config = config or {}
        self.app = ConfigManager.get_config_value(self.config, 'app')
        self.logger = Logger(log2Console=True)
        self.cacheService = cacheService
        self.tenantRepository = tenantRepository
        self.commonHelper = commonHelper

        (_, _, _, _, _, _, self.refereesById, self.refereesByInternalId) = referees_data

        self.adminMobile = ConfigManager.get_config_value(self.config, 'adminMobile')
        self.apiServiceUrlBase = ConfigManager.get_config_value(self.config, 'apiServiceUrlBase')
        self.docsServiceUrlBase = ConfigManager.get_config_value(self.config, 'docsServiceUrlBase')

        self.activeClient = activeClient
        self.useMeta = metaClient and metaClient.useClient
        self.useTwilio = twilioClient and twilioClient.useClient
        self.useGreenApi = greenApiClient and greenApiClient.useClient
        self.useManychat = manychatClient and manychatClient.useClient
        self.useTelegram = telegramClient and telegramClient.useClient

        # Use injected clients if provided, otherwise create them (backward compatibility)
        self.twilioClient = twilioClient
        self.telegramClient = telegramClient

        # Use injected GreenApi client if provided, otherwise create it (backward compatibility)
        self.greenApiClient = greenApiClient
        if self.useGreenApi:
            self.greenApiFromChatId = self.greenApiClient.getChatId(to=self.greenApiClient.fromMobile)
            self.addNonActiveRefereesToGroups = ConfigManager.get_config_bool(self.config, 'addNonActiveRefereesToGroups', False)
            self.adminChatId = self.greenApiClient.getChatId(to=self.adminMobile)
            self.checkInstanceState()
            if self.useGreenApi == False:
                self.logger.warning(f'GreenApi not authorized')
                # Schedule message to be sent asynchronously
                try:
                    response = self.greenApiClient.rebootInstance()
                    self.logger.info(f"GreenApi rebootInstance response: {response}")
                    self.checkInstanceState()
                    '''
                    # Try to get the running event loop
                    loop = asyncio.get_running_loop()
                    # If we have a running loop, create a task
                    asyncio.create_task(self.sendMessage(
                        to=self.adminMobile, 
                        message=f'GreenApi not authorized, stateInstance={getStateInstance.get('stateInstance')}', 
                        title='GreenApi not authorized'
                    ))
                    '''
                except RuntimeError:
                    # No event loop running, create a new one
                    # This will run in a separate thread to avoid blocking
                    def send_init_message():
                        try:
                            current_state = self.greenApiClient.getStateInstance()
                            asyncio.run(self.sendMessage(
                                to=self.adminMobile, 
                                message=f'GreenApi not authorized, stateInstance={current_state.get("stateInstance")}', 
                                title='GreenApi not authorized'
                            ))
                        except Exception as e:
                            self.logger.error(f"Failed to send init message: {str(e)}")
                    
                    import threading
                    thread = threading.Thread(target=send_init_message, daemon=True)
                    thread.start()

        # Use injected ManyChat client if provided, otherwise create it (backward compatibility)
        self.manychatClient = manychatClient

        # Use injected Meta client if provided, otherwise create it (backward compatibility)
        self.metaClient = metaClient

        # Use injected message templates if provided, otherwise use environment variables
        self.useMessageTemplates = useMessageTemplates
        if messageTemplates:
            self.messageTemplates = messageTemplates
            # Set template variables directly from injected templates
            self.newGameMessageTemplate = self.messageTemplates.get('newGame')
            self.gameUpdateMessageTemplate = self.messageTemplates.get('gameUpdate')
            self.gameNoticeMessageTemplate = self.messageTemplates.get('gameNotice')
            self.menuMessageTemplate = self.messageTemplates.get('menu')
            self.onBoardingActivateMessageTemplate = self.messageTemplates.get('onBoardingActivate')
            self.onBoardingJoinConfirmationMessageTemplate = self.messageTemplates.get('onBoardingJoinConfirmation')
            self.onBoardingRegistrationMessageTemplate = self.messageTemplates.get('onBoardingRegistration')
            self.openWindowMessageTemplate = self.messageTemplates.get('openWindow')
            self.gamePortalCodeMessageTemplate = self.messageTemplates.get('gamePortalCode')
            self.loginOtpMessageTemplate = self.messageTemplates.get('loginOtp')

        self.vapidPrivateKey = helpers.get_secret('vapid_private_key')
        self.apnsClient = ApnsClient(logger=self.logger, config=self.config)
        self.mqttPublish = ConfigManager.get_config_bool(self.config, 'mqttPublish', True)
        self.mqttClient = MqttClient(
            ConfigManager.get_config_value(
                self.config,
                'app_env',
                ConfigManager.get_config_value(self.config, 'env')
            ),
            self.logger
        )
        self.mqttTopic = 'my/mqtt/refPortal'

        self.brevoApiKey = helpers.get_secret('refereex_brevo_apikey')
        self.brevoApiUrl = ConfigManager.get_config_value(self.config, 'brevoApiUrl')

        self.logger.debug('Before firebase')
        # Initialize Firebase Admin SDK
        jsonKeyFile = "path/to/your/serviceAccountKey.json"
        if os.path.exists(jsonKeyFile):
            fbCred = credentials.Certificate(jsonKeyFile)
            firebase_admin.initialize_app(fbCred)
        self.logger.debug('After firebase')

        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            "games" : {
                'title': 'שיבוצים',
                'generate': self.commonHelper.generateGameDetails
            },
            "reviews": {
                'title': 'ביקורות',
                'generate': self.commonHelper.generateReviewDetails
            }
        }

        self.msgLogger = Logger(config=self.config)

        self.logger.info(f'MessagingService starts... twilio={self.twilioClient and self.twilioClient.useClient} greenApi={self.greenApiClient and self.greenApiClient.useClient} manychat={self.manychatClient and self.manychatClient.useClient} meta={self.metaClient and self.metaClient.useClient} telegram={self.telegramClient and self.telegramClient.useClient} mqtt={self.mqttPublish}')

        if self.metaClient and self.useMeta:
            self.metaClient.register_delivery_failure_hook(self._meta_delivery_failure_hook)

    async def _meta_delivery_failure_hook(self, to_number, wamid, message_record, errors):
        try:
            asyncio.create_task(
                self._handle_meta_delivery_failure(to_number, wamid, message_record, errors)
            )
        except Exception as ex:
            self.logger.error('meta delivery failure schedule', ex)

    def _meta_retry_resolve_dest(self, message_record: dict, to_number: str) -> str:
        dest = message_record.get('to') if isinstance(message_record, dict) else None
        if isinstance(dest, list) and len(dest) > 0:
            dest = dest[0]
        if not dest:
            dest = to_number
        return _adjustMobileNo(mobileNo=dest)

    def _meta_retry_extract_body_preview_title(self, message_record: dict) -> Tuple[Optional[str], bool, Optional[str]]:
        if not isinstance(message_record, dict):
            return None, False, None
        if message_record.get('type') == 'text':
            t = message_record.get('text') or {}
            body = t.get('body')
            preview = bool(t.get('preview_url'))
            if body:
                return body, preview, None
        msg = message_record.get('message')
        if msg is not None:
            return msg, bool(message_record.get('previewUrl')), message_record.get('title')
        return None, False, None

    def _meta_retry_compose_message_for_greenapi(self, body: Optional[str], title: Optional[str]) -> Optional[str]:
        if not body:
            return None
        if title:
            return f'{title}\n{body}'
        return body

    async def _meta_retry_send_greenapi(self, to_number: str, body: Optional[str], title: Optional[str], preview: bool) -> None:
        text = self._meta_retry_compose_message_for_greenapi(body, title)
        if not text:
            self.logger.warning('meta fallback GreenApi: empty message text, skip')
            return
        if not self.useGreenApi or not self.checkSendGreenApiMessages(to=to_number):
            self.logger.warning('meta fallback GreenApi: GreenApi unavailable or disabled for this user')
            return
        try:
            sid = await self.greenApiSendMessage(to=to_number, message=text, previewUrl=preview)
            self.logger.info(f'meta delivery fallback sent via GreenApi to={to_number} sid={sid}')
        except Exception as ex:
            self.logger.error('meta delivery fallback GreenApi failed', ex)

    async def _handle_meta_delivery_failure(self, to_number, wamid, message_record, errors) -> None:
        if not self.useMeta or not self.metaClient:
            return
        lock_prop = f'metaDeliveryRetryLock:{wamid}'
        if self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=to_number, propertyName=lock_prop):
            return
        self.cacheService.setCacheOnlyKeyVal(
            tenantKey='GLOBAL',
            mobileNo=to_number,
            propertyName=lock_prop,
            value={'v': True},
            ttlSeconds=120,
        )
        try:
            attempt = int(message_record.get('metaOutboundAttempt', 1) or 1)
            body, preview, title = self._meta_retry_extract_body_preview_title(message_record)
            dest = self._meta_retry_resolve_dest(message_record, to_number)
            self.logger.info(
                f'meta delivery retry: to={dest} wamid={wamid} attempt={attempt}/{self.META_DELIVERY_MAX_META_ATTEMPTS} hasBody={bool(body)}'
            )

            if attempt < self.META_DELIVERY_MAX_META_ATTEMPTS:
                if body:
                    new_sid = self.metaClient.sendMessage(
                        to=dest,
                        message=body,
                        title=title,
                        previewUrl=preview,
                        replyToMessageId=None,
                        referee_message_extra={'metaOutboundAttempt': attempt + 1},
                    )
                    if not new_sid:
                        self.logger.error('meta delivery retry: sendMessage returned no sid')
                else:
                    self.logger.warning(
                        'meta delivery retry: no extractable body (e.g. template only); trying GreenApi before exhausting Meta attempts'
                    )
                    await self._meta_retry_send_greenapi(dest, body, title, preview)
                return

            await self._meta_retry_send_greenapi(dest, body, title, preview)
            err0 = errors[0] if errors else {}
            self.cacheService.setCacheOnlyKeyVal(
                tenantKey='GLOBAL',
                mobileNo=to_number,
                propertyName='failedMessageToMeta',
                value={
                    'status': 'failed',
                    'errorCode': err0.get('code'),
                    'errorMessage': err0.get('message'),
                    'metaRetriesExhausted': True,
                },
                ttlSeconds=60 * 60 * 24,
            )
        finally:
            self.cacheService.setCacheOnlyKeyVal(
                tenantKey='GLOBAL',
                mobileNo=to_number,
                propertyName=lock_prop,
                value=None,
                ttlSeconds=-1,
            )

    def checkInstanceState(self):
        getStateInstance = self.greenApiClient.getStateInstance()
        self.useGreenApi = getStateInstance.get('stateInstance') == 'authorized'
        pass

    async def incomingWebhookCheckWindow(self, source:str, fromMobileNo:str, request:Request):
        # App-originated chat (see incomingWebhookFromApp) has no provider client to verify
        # against - it's already JWT-authenticated before it ever reaches here - and no WhatsApp
        # messaging-window concept applies to it either.
        if source == 'app':
            return True

        sourceClient = None
        if source == 'twilio':
            sourceClient = self.twilioClient
        elif source == 'greenApi':
            sourceClient = self.greenApiClient
        elif source == 'meta':
            sourceClient = self.metaClient
        elif source == 'telegram':
            sourceClient = self.telegramClient

        isIncomingMessage = await sourceClient.isIncomingMessage(request=request)
        if isIncomingMessage:
            localNow = helpers.localNow()
            self.cacheService.setCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=fromMobileNo, propertyName='24HoursWindowStarts', value=localNow, ttlSeconds=24*60*60)

        return isIncomingMessage
    
    def checkIf24HoursWindowIsOpen(self, mobileNo):
        localNow = helpers.localNow()
        window24HoursStarts = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='24HoursWindowStarts') or False
        if window24HoursStarts:
            return True
        
        recentMessages = self.cacheService.getRefereeMessages(mobileNo=mobileNo, direction='FROM', recentDays=1)
        if len(recentMessages) > 0:
            lastMessage = next(iter(recentMessages.values()))
            ttlSeconds = int((localNow - lastMessage['created']).total_seconds())
            if ttlSeconds < 24 * 60 * 60:
                self.cacheService.setCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='24HoursWindowStarts', value=lastMessage['created'], ttlSeconds=24*60*60-ttlSeconds)
                return True
        
        return False

    async def sendIceBreaker(self, refereeDetail, message):
        sendRegisterReminderContentSid = ConfigManager.get_config_value(self.config, 'twilioOpenWindow')
        
        if not self.useTwilio:
            return
        
        if False and not (self.twilioUseTemplate and sendRegisterReminderContentSid):
            message = f'{message} על מנת להמשיך לקבל הודעות נא ללחוץ על הקישור הבא\n{renewUrl}'
            msgSid = await self.twilioClient.sendMessage(to=refereeDetail['mobileNo'], message=message)

        else:
            name = refereeDetail['name']
            if message:
                name = f'{name}, {message}'
            msgSid = self.twilioClient.sendUsingContentTemplate(refereeDetail['mobileNo'], sendRegisterReminderContentSid, {'name': name})#, 'message': message})
    
    async def sendIceBreakerToUser(self, toMobile: str, toName: str = None, customMessage: str = None, templateSid: str = None, templateVariables: dict = None, sendAt: str = None):
        """
        Send an Ice Breaker message to a specific user.
        
        Args:
            toMobile (str): The mobile number of the recipient
            toName (str, optional): The name of the recipient. If None, will use 'User'
            customMessage (str, optional): Custom message to include with the Ice Breaker
            templateSid (str, optional): Custom template SID. If None, uses default twilioOpenWindow
            templateVariables (dict, optional): Variables for the template
            sendAt (str, optional): ISO 8601 timestamp for scheduled sending
            
        Returns:
            str: Message SID if successful, None otherwise
        """
        try:
            # Use default template if none provided
            if not templateSid:
                templateSid = ConfigManager.get_config_value(self.config, 'twilioOpenWindow')
            
            if not templateSid:
                self.logger.warning(f'No template SID provided for Ice Breaker to {toMobile}')
                return None
            
            # Prepare template variables
            if not templateVariables:
                templateVariables = {}
            
            # Set name - use provided name or default to 'User'
            recipientName = toName if toName else 'User'
            if customMessage:
                recipientName = f'{recipientName}, {customMessage}'
            
            templateVariables['name'] = recipientName
            
            msgSid = None
            
            # Send via Twilio if enabled
            if self.twilioClient.useClient and self.useMessageTemplates:
                msgSid = self.twilioClient.sendUsingContentTemplate(
                    toMobile=toMobile, 
                    contentSid=templateSid, 
                    contentVariables=templateVariables, 
                    sendAt=sendAt
                )
                self.logger.info(f'Sent Ice Breaker via Twilio to {toMobile}, msgSid: {msgSid}')
            
            # Send via Meta/WhatsApp if enabled
            elif self.metaClient.useClient:
                # Convert template variables to Meta format if needed
                metaVariables = templateVariables.copy()
                msgSid = self.metaClient.sendTemplateMessage(
                    to=toMobile,
                    templateName=templateSid,  # Meta uses template name, not SID
                    languageCode="he",
                    components=[{"type": "body", "parameters": [{"type": "text", "text": recipientName}]}]
                )
                self.logger.info(f'Sent Ice Breaker via Meta to {toMobile}, msgSid: {msgSid}')
            
            # Send via Green API if enabled
            elif self.greenApiClient.useClient:
                # Green API doesn't support templates directly, send as regular message
                message = f"שלום {recipientName}"
                if customMessage:
                    message += f", {customMessage}"
                msgSid = await self.greenApiSendMessage(to=toMobile, message=message)
                self.logger.info(f'Sent Ice Breaker via Green API to {toMobile}, msgSid: {msgSid}')
            
            # Send via ManyChat if enabled
            elif self.manychatClient.useClient:
                # ManyChat implementation would go here
                self.logger.info(f'ManyChat Ice Breaker not implemented yet for {toMobile}')
                return None
            
            else:
                self.logger.warning(f'No messaging service enabled for Ice Breaker to {toMobile}')
                return None
            
            # Log the Ice Breaker attempt
            self.logger.info(f'Ice Breaker sent to {toMobile} (name: {recipientName}, template: {templateSid})')
            
            return msgSid
            
        except Exception as ex:
            self.logger.error(f'Error sending Ice Breaker to {toMobile}:', ex)
            return None
    
    def checkSendGreenApiMessages(self, to):
        createGroups = None
        refereeDetail = to
        if isinstance(to, str):
            refereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=to)

        if refereeDetail:
            createGroups = refereeDetail.get('createGroups') or False        
            return self.useGreenApi and createGroups
        
        return False
    
    async def sendOpenWindowMessage(self, toMobile, toName):
        openwindow = self.openWindowMessageTemplate
        bodyParameters = {
            'name': toName
        }
        msgSid = self.metaClient.sendTemplateMessage(
            to=toMobile,
            templateName=openwindow,
            languageCode="he",
            components=[{"type": "body", "parameters": [{"type": "text", "text": toName}]}]
        )
        return msgSid

    async def sendGamePortalCodeMessage(self, toMobile, toName, gameTitle, portalCode):
        windowIsOpen = self.checkIf24HoursWindowIsOpen(mobileNo=toMobile)
        gamePortalCode = self.gamePortalCodeMessageTemplate
        bodyParameters = {
            'name': toName,
            'gameTitle': gameTitle,
            'portalCode': portalCode
        }
        msgSid = self.metaClient.sendGamePortalCodeMessage(
            toMobile=toMobile,
            bodyParameters=bodyParameters,
            sendTemplate=not windowIsOpen,
            templateName=gamePortalCode,
        )
        return msgSid

    async def sendLoginOtpMessage(self, toMobile, code):
        # Not routed through sendGamePortalCodeMessage's generic template path: an AUTHENTICATION-
        # category template's COPY_CODE button requires its own "button"/"copy_code" component
        # (with the code repeated as a coupon_code parameter) alongside the body parameter, which
        # generateTemplatePayload doesn't build. Within an open session window we skip the
        # approved-template wording entirely and just send the code as plain text.
        windowIsOpen = self.checkIf24HoursWindowIsOpen(mobileNo=toMobile)
        if windowIsOpen:
            return self.metaClient.sendMessage(to=toMobile, message=f"קוד האימות שלך למערכת RefereeX: {code}")

        components = [
            {"type": "body", "parameters": [{"type": "text", "text": code}]},
            {"type": "button", "sub_type": "copy_code", "index": "0", "parameters": [{"type": "coupon_code", "coupon_code": code}]}
        ]
        return self.metaClient.sendTemplateMessage(
            to=toMobile,
            templateName=self.loginOtpMessageTemplate,
            languageCode="he",
            components=components,
        )

    async def sendNewGameNotification(self, refereeGame, title, refId, toMobile, toName, sendAt=None, skipPushNotification=False):
        newgame = self.newGameMessageTemplate      
        tenantKey = refereeGame['tenantKey']
        windowIsOpen = self.checkIf24HoursWindowIsOpen(mobileNo=toMobile)
        globalRefereeDetails = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=toMobile)
        sendMessagesToTelegram = globalRefereeDetails.get('telegramId') and globalRefereeDetails.get('sendMessagesToTelegram', False) or False
        
        gameDumps = jsonHelper.save_to_json(refereeGame)
        msgSid = str(uuid.uuid4())[:8]

        gameDetail = self.cacheService.getGameDetail(game=refereeGame)
        if not gameDetail:
            self.logger.warning(f'sendNewGameNotification: no gameDetail resolved for game, skipping', refereeDetail=globalRefereeDetails)
            return None, []
        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], game=refereeGame)
        includeReferees = True
        includeReviewer = False
        if tournament:
            rule = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules'))
            includeReviewer = rule.include_reviewer if rule else False

        icsFileUrl = f'{self.apiServiceUrlBase}api/file/{gameDetail["id"]}'
        self.logger.info(f'sendNewGameNotification icsFileUrl={icsFileUrl}')

        dateText = ''
        if gameDetail.get('dow'):
            dateText += gameDetail.get('dow') + ' '
        dateText += gameDetail.get('dateText')
        nameParameter = f'{toName or globalRefereeDetails.get('name')} *({refereeGame.get('role')})*'
        refereesText = self.commonHelper.generateGameReferees(tenantKey=tenantKey, gameDetail=gameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer) or '...'
        if gameDetail.get('comment'):
            refereesText += f'\n{gameDetail.get('comment')}'
        bodyParameters = {
            'name': nameParameter,
            'date': dateText,
            'tournament': gameDetail.get('tournamentName'),
            'game': gameDetail.get('gameTitle'),
            'role': f"{refereeGame.get('role')}{'*' if len(gameDetail.get('referees')) > 1 else ''}",
            'round': gameDetail.get('round'),
            'week': gameDetail.get('fixture'),
            'field': gameDetail.get('fieldName'),
            'status': refereeGame.get('status'),
            'referees': refereesText,
            #'comment': gameDetail.get('gameComment'),
            #'gameId': gameDetail['id'],
            #'fileId': fileId
        }

        message = f"{title}\n{self.dataDic['games']['generate'](tenantKey=tenantKey, gameDetail=refereeGame | gameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)}"
        message += f'\nעדכון לוח שנה {icsFileUrl}'
        
        if (self.activeClient == 'twilio'):
            if not self.checkSendGreenApiMessages(to=toMobile):
                approveUrl = f'{self.apiServiceUrlBase}api/approveGame/{refId}/{msgSid}/{gameDetail["id"]}'
                message += f'\nניתן לאשר אוטומטית בפורטל דרך הקישור הבא {approveUrl}'
            msgSid = await self.sendMessage(to=toMobile, message=message, title=title)
            self.logger.info(f'sendNewGameNotification sendMessage={msgSid}')
            if self.checkSendGreenApiMessages(to=toMobile):
                message = f"{title}\n{self.dataDic['games']['generate'](tenantKey=tenantKey, gameDetail=refereeGame | gameDetail, includeReferees=False)}"
                self.logger.info(f'sendNewGameNotification sendPoll={message}')
                msgSid = await self.sendPoll(to=toMobile, message=message, options=['לאשר בפורטל', 'לא לאשר'], extra=f'approveGame_{gameDetail["id"]}')
                self.logger.info(f'sendNewGameNotification sendPoll={msgSid}')

        elif (self.activeClient == 'meta'):
            useGreenApi = False
            failedMessageToMeta = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=toMobile, propertyName='failedMessageToMeta')
            if failedMessageToMeta and failedMessageToMeta.get('errorCode') in ['131026', '131000', '130472']:
                useGreenApi = True
            if useGreenApi:
                message = f"{title}\n{self.dataDic['games']['generate'](tenantKey=tenantKey, gameDetail=refereeGame | gameDetail, includeReferees=False)}"
                self.logger.info(f'sendNewGameNotification sendPoll={message}')
                msgSid = await self.sendPoll(to=toMobile, message=message, options=['לאשר בפורטל', 'לא לאשר'], extra=f'approveGame_{gameDetail["id"]}')
                self.logger.info(f'sendNewGameNotification sendPoll={msgSid}')
            else:
                msgSid = self.metaClient.sendNewGameNotification(toMobile=toMobile, bodyParameters=bodyParameters, gameDetail=gameDetail, templateName=newgame, sendTemplate=False if windowIsOpen else True, sendAt=sendAt)

        if sendMessagesToTelegram and False:
            msgSid = self.telegramClient.sendNewGameNotification(chatId=globalRefereeDetails.get('telegramId'), mobileNo=toMobile, bodyParameters=bodyParameters, gameDetail=gameDetail, templateName=newgame, sendAt=sendAt)

        if msgSid:
            msgLog = {
                'origin': 'system',
                'type': 'sendNewGameNotification',
                'to': toMobile,
                'toName': toName,
                'bodyParameters': bodyParameters,
                'templateName': newgame,
                'msgSid': msgSid,
                'gameId': gameDetail['id'],
            }
            self.msgLogger.info(msgLog)

        if self.useMessageTemplates and newgame and self.useTwilio:
            msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=newgame, contentVariables=bodyParameters, mediaUrl=icsFileUrl, sendAt=sendAt)

        pushTitle = title
        pushTitle += gameDetail.get('tournamentName')
        pushTitle += ' ' +gameDetail.get('gameTitle')
        sentPushMsgIds = []
        if not skipPushNotification:
            sentPushMsgIds = self.sendPushNotification(
                to=toMobile, title=pushTitle, body=message, url=icsFileUrl, section='games', gameId=gameDetail['id'],
                category='NEW_GAME_ASSIGNMENT'
            )
            refereeGame['newPushMsgIds'] = sentPushMsgIds

        refereeGame['newMessageSid'] = msgSid

        if self.mqttPublish:
            self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=gameDumps, refId=refId)

        return msgSid, sentPushMsgIds
    
    async def sendGameUpdateNotification(self, refereeGames, gameRemoval, title, refId, toMobile, toName, sendAt=None, skipPushNotification=False, internalMsgId:str=None):
        gamesupdate = self.gameUpdateMessageTemplate
        msgSid = None
        sentPushMsgIds = []
        message = ''
        
        for gamePk, refereeGame in refereeGames.items():
            tenantKey = refereeGame['tenantKey']
            if message:
                message += '\n\n'
            gameDetail = self.cacheService.getGameDetail(game=refereeGame)
            if not gameDetail:
                self.logger.warning(f'sendGameUpdateNotification: no gameDetail resolved for game {gamePk}, skipping')
                continue
            tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'], game=refereeGame)
            useGreenApi = self.checkSendGreenApiMessages(to=toMobile)
            includeReferees = True
            includeReviewer = False
            msgToGroup = False
            if gameRemoval:
                includeReferees = False
            elif tournament:
                rule = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament.get('rules'))
                includeReviewer = rule.include_reviewer if rule else False

            icsFileUrl = f'{self.apiServiceUrlBase}api/file/{gameDetail["id"]}'

            if useGreenApi and gameDetail.get('chatGroupId') and len(gameDetail.get('referees')) > 1:
                msgToGroup = True

            bodyParameters = {
                'name': toName,
                'title': title,
                'date': f"{gameDetail.get('dow')} {gameDetail.get('date')}",
                'tournament': gameDetail.get('tournamentName'),
                'game': gameDetail.get('gameTitle'),
                'role': f"{refereeGame.get('role')}{'*' if len(gameDetail.get('referees')) > 1 else ''}",
                'round': gameDetail.get('round'),
                'week': gameDetail.get('fixture'),
                'field': gameDetail.get('fieldName'),
                'status': refereeGame.get('status'),
                'referees': self.commonHelper.generateGameReferees(tenantKey=tenantKey, gameDetail=gameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer) or '...',
                'fileId': gameDetail["id"]
            }

            if msgToGroup == True:
                gameDetail1 = gameDetail
            else:
                gameDetail1 = gameDetail | refereeGame

            message += f"{title}\n{self.dataDic['games']['generate'](tenantKey=tenantKey, gameDetail=gameDetail1, includeReferees=includeReferees, includeReviewer=includeReviewer)}"
            message += f'\nעדכן לוח שנה {icsFileUrl}'

            if self.useMessageTemplates and gamesupdate and self.useTwilio:                
                msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=gamesupdate, contentVariables=bodyParameters, mediaUrl=icsFileUrl, sendAt=sendAt)
                refereeGame['changedMessageSid'] = msgSid

        if not gameRemoval:
            to = gameDetail
        else:
            to = toMobile

        msgSid, sentPushMsgIds = await self.sendMessage(
            to=to,
            message=message,
            performOpenWindowCheck=True,
            skipPushNotification=skipPushNotification,
            returnSentPushMsgIds=True,
            internalMsgId=internalMsgId,
            gameId=gameDetail['id'],
            pushSection='games',
        )

        for gamePk, refereeGame in refereeGames.items():
            refereeGame['changedMessageSid'] = msgSid
            if sentPushMsgIds:
                refereeGame['changedPushMsgIds'] = sentPushMsgIds

        gameDumps = jsonHelper.save_to_json(refereeGames)

        if self.mqttPublish:
            self.mqttClient.publish(topic=self.mqttTopic, title='שיבוץ', payload=gameDumps, refId=refId)

        return msgSid, sentPushMsgIds

    async def sendNewReviewNotification(self, reviews, title, refId, toMobile, toName, sendAt=None, skipPushNotification=False, internalMsgId:str=None):
        newreview = ConfigManager.get_config_value(self.config, 'twilioNewReviewContentSid')
        msgSid = None
        sentPushMsgIds = []
        gameDetail = None

        for gamePk, refereeReview in reviews.items():
            tenantKey = refereeReview['tenantKey']
            gameDetail = self.cacheService.getGameDetail(game=refereeReview)
            message = self.dataDic['reviews']['generate'](tenantKey=tenantKey, gameDetail=refereeReview)

            if self.useMessageTemplates and newreview and self.useTwilio:
                variables = {
                    'date': f"{refereeReview.get('date')} {refereeReview.get('time')}",
                    'tournament': refereeReview.get('tournamentName'),
                    'game': refereeReview.get('gameTitle'),
                    'field': refereeReview.get('field'),
                    'week': refereeReview.get('round'),
                    'jobTitle': refereeReview.get('role'),
                    'reviewer': refereeReview.get('reviewer'),
                    'grade': refereeReview.get('reviewGrade')
                }
                msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=newreview, contentVariables=variables, sendAt=sendAt)
                refereeReview['newMessageSid'] = msgSid

            if not (self.useMessageTemplates and newreview):
                msgSid, sentPushMsgIds = await self.sendMessage(
                    to=toMobile,
                    message=message,
                    title=title,
                    sendAt=sendAt,
                    performOpenWindowCheck=True,
                    skipPushNotification=skipPushNotification,
                    returnSentPushMsgIds=True,
                    internalMsgId=internalMsgId,
                    gameId=gameDetail['id'],
                    pushSection='reviews',
                )
                refereeReview['newMessageSid'] = msgSid
                if sentPushMsgIds:
                    refereeReview['newPushMsgIds'] = sentPushMsgIds

        reviewDumps = jsonHelper.save_to_json(reviews)

        if self.mqttPublish:
            self.mqttClient.publish(topic=self.mqttTopic, title='ביקורת', payload=reviewDumps, refId=refId)

        return msgSid, sentPushMsgIds

    async def sendReviewUpdateNotification(self, reviews, reviewRemoval, title, refId, toMobile, toName, sendAt=None, skipPushNotification=False, internalMsgId:str=None):
        reviewsupdate = ConfigManager.get_config_value(self.config, 'twilioReviewUpdateContentSid')
        msgSid = None
        sentPushMsgIds = []
        gameDetail = None

        for gamePk, refereeReview in reviews.items():
            tenantKey = refereeReview['tenantKey']
            gameDetail = self.cacheService.getGameDetail(game=refereeReview)
            message = self.dataDic['reviews']['generate'](tenantKey=tenantKey, gameDetail=refereeReview)

            if self.useMessageTemplates and reviewsupdate and self.useTwilio:
                variables = {
                    'action': title,
                    'date': f"{refereeReview.get('date')} {refereeReview.get('time')}",
                    'tournament': refereeReview.get('tournamentName'),
                    'game': refereeReview.get('gameTitle'),
                    'field': refereeReview.get('field'),
                    'week': refereeReview.get('round'),
                    'jobTitle': refereeReview.get('role'),
                    'reviewer': refereeReview.get('reviewer'),
                    'grade': refereeReview.get('reviewGrade')
                }
                msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=toMobile, contentSid=reviewsupdate, contentVariables=variables, sendAt=sendAt)
                refereeReview['changedMessageSid'] = msgSid

            if not (self.useMessageTemplates and reviewsupdate):
                msgSid, sentPushMsgIds = await self.sendMessage(
                    to=toMobile,
                    message=message,
                    title=title,
                    sendAt=sendAt,
                    performOpenWindowCheck=True,
                    skipPushNotification=skipPushNotification,
                    returnSentPushMsgIds=True,
                    internalMsgId=internalMsgId,
                    gameId=gameDetail['id'] if gameDetail else None,
                    pushSection='reviews',
                )
            refereeReview['changedMessageSid'] = msgSid
            if sentPushMsgIds:
                refereeReview['changedPushMsgIds'] = sentPushMsgIds

        reviewDumps = jsonHelper.save_to_json(reviews)

        if self.mqttPublish:
            self.mqttClient.publish(topic=self.mqttTopic, title='ביקורת', payload=reviewDumps, refId=refId)

        return msgSid, sentPushMsgIds

    async def sendMenuContent(self, refereeDetail):
        if self.checkSendGreenApiMessages(to=refereeDetail):
            message = f'אהלן {refereeDetail["name"]}, זה הבוט של RefereeX ואני רוצה להציע לך לבחור מהתפריט הבא'
            options = [ 'שיבוצים', 'שיבוצים קצר', 'ביקורות', 'מידע', 'תמיכה']
            msgSid = await self.sendPoll(to=refereeDetail['mobileNo'], message=message, options=options)
        elif self.useTwilio:
            contentVariables = { 'name': refereeDetail['name'] }
            msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=refereeDetail['mobileNo'], contentSid=self.twilioMenuContentSid, contentVariables=contentVariables)
        return msgSid

    async def sendOnBoardingActivate(self, refereeDetail):
        if self.checkSendGreenApiMessages(to=refereeDetail):
            msgSid = await self.sendPoll(to=self.adminMobile, message=f'אישור רישום לשופט {refereeDetail["name"]}', options=['מאשר', 'לא מאשר'], extra=f'activate_{refereeDetail["refId"]}')
        elif self.useTwilio:
            contentVariables = { 'refId': refereeDetail['refId'], 'refName': refereeDetail['name'] }
            msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=self.adminMobile, contentSid=self.twilioOnBoardingActivate, contentVariables=contentVariables)
        return msgSid

    async def sendOnBoardingJoinConfirmation(self, to, forceUseGreenApi=False):
        sentPushMsgIds = self.sendPushNotification(to=to, title='נשלחה אליך בקשת אישור הצטרפות לשירות הודעות לשופטים')

        if forceUseGreenApi or self.checkSendGreenApiMessages(to=to):
            contactDetails = await self.getContactInfo(to=to)
            msgSid = await self.sendPoll(to=to, message=f'אהלן {contactDetails.get("name")}, האם את/ה מאשר/ת הצטרפות לשירות הודעות לשופטים ?', options=['כן', 'לא'], extra=f'approveJoin_{to}')
        elif self.useTwilio:
            msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=to, contentSid=self.twilioOnBoardingJoinConfirmation)
        return msgSid

    async def sendOnBoardingRegistration(self, to):
        if self.checkSendGreenApiMessages(to=to):
            contactDetails = await self.getContactInfo(to=to)
            msgSid = await self.sendMessage(to=to, message=f'אהלן שוב {contactDetails.get("name")}, נא ללחוץ על הקישור ולעדכן את פרטי השופט \n https://www.refereex.com/registration')
        elif self.useTwilio:
            msgSid = self.twilioClient.sendUsingContentTemplate(toMobile=to, contentSid=self.twilioOnBoardingRegistration)
        return msgSid

    async def sendGeneralNotification(self, refereeDetail, noticeTitle, noticeDetails, sendAt=None, internalMsgId:str=None):
        msgSid = None

        noticeDetails1 = noticeDetails.replace('"','\"')
        msgSid = await self.sendMessage(to=refereeDetail['mobileNo'], message=f'{noticeTitle}\n{noticeDetails1}', sendAt=sendAt, performOpenWindowCheck=True, internalMsgId=internalMsgId)

        return msgSid

    async def sendFreeTextMessage(self, title, message, refId, toMobile, toName, sendAt=None, internalMsgId:str=None):
        msgSid = None
        message1 = message.replace('"','\"')

        msgSid = await self.sendMessage(to=toMobile, message=message1, title=title, sendAt=sendAt, performOpenWindowCheck=True, internalMsgId=internalMsgId)

        if self.mqttPublish:
            self.mqttClient.publish(topic=self.mqttTopic, title=title, payload=message1, refId=refId)

        return msgSid

    @staticmethod
    def adjustMobileNo(mobileNo) -> str:
        return _adjustMobileNo(mobileNo)

    def allowMessageSending(self, to) -> bool:
        globalRefereeDetail = None
        if isinstance(to, dict):
            globalRefereeDetail = to
        elif isinstance(to, str):
            globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=to)
        elif isinstance(to, list):
            for mobileNo in to:
                globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
                if globalRefereeDetail:
                    break
        else:
            return False

        messageAcceptanceLimitation = helpers.to_bool(globalRefereeDetail.get('messageAcceptanceLimitation'), default=True)
        localTime = helpers.localNow()
        localHour = localTime.hour
        availableFromHour = int(globalRefereeDetail.get('availableFromHour', '7'))
        availableToHour = int(globalRefereeDetail.get('availableToHour', '21'))
        if messageAcceptanceLimitation:
            if availableFromHour <= availableToHour and (localHour < availableFromHour or localHour > availableToHour) \
                    or availableFromHour > availableToHour and (localHour > availableFromHour and localHour < availableToHour):
                return False
        return True

    def applyMessageAcceptanceLimitation(self):
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    globalRefereeDetail = kwargs.get('globalRefereeDetail')
                    if not globalRefereeDetail:
                        raise Exception('globalRefereeDetail is required')
                    allowMessageSending = self.allowMessageSending(to=globalRefereeDetail)
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    self.logger.error(f'availableToMessage error: {e}')
                    return None
            return wrapper
        return decorator

    async def useTwilioMessage(self, to:str, message:str, previewUrl:bool=False):
        to = _adjustMobileNo(mobileNo=to)
        msgSid = await self.twilioClient.sendMessage(to=to, message=message, previewUrl=previewUrl)
        return msgSid

    async def greenApiSendMessage(self, to:str, message:str, previewUrl:bool=False):
        msgSid = await self.greenApiClient.handleAction('sendMessage', {'to': to, 'message': message, 'previewUrl': previewUrl})
        return msgSid

    async def greenApiSendLocation(self, to: str, latitude:str, longitude:str, name:str, address:str):
        msgId = await self.greenApiClient.handleAction('sendLocation', {'to': to, 'latitude': latitude, 'longitude': longitude, 'name': name, 'address': address})
        return msgId
    
    def setRefereeMessage(self, mobileNo, direction:str, title:str, message:str, previewUrl:bool, sendAt:str, forceUseGreenApi:bool, skipPushNotification:bool, msgSid:str, source:str):
        try:
            if isinstance(mobileNo, list):
                mobileNos = mobileNo
            else:
                mobileNos = [mobileNo]

            for _mobileNo in mobileNos:
                value = {
                    'to': _mobileNo,
                    'source': source,
                    'message': message,
                    'title': title,
                    'previewUrl': previewUrl,
                    'sendAt': sendAt,
                    'forceUseGreenApi': forceUseGreenApi,
                    'skipPushNotification': skipPushNotification,
                    'activeClient': self.activeClient,
                    'metaOutboundAttempt': 1,
                }
                self.cacheService.setRefereeMessage(mobileNo=mobileNo, direction=direction, msgSid=msgSid, value=value)
        except Exception as ex:
            self.logger.error(f'setRefereeMessage error', ex)
            return None

    async def sendMessageToList(self, to, message:str, title:str=None, previewUrl:bool=False, forceUseGreenApi:bool=False, skipPushNotification:bool=False, replyToMessageId:str=None, performOpenWindowCheck:bool=False, internalMsgId:str=None, gameId:str=None, pushSection:str=None, pushCategory:str=None, leaveByTime:str=None) -> tuple[str, list]:
        msgSid = None
        localNow = helpers.localNow()
        mobileNos = to['activeGroupMobileNumbers'] if isinstance(to, dict) and 'activeGroupMobileNumbers' in to else (to if isinstance(to, list) else [to])
        sentPushMsgIds = []
        
        # If window is open - message sent by Meta and push
        # If window is closed, message sent by push, Open Window request is sent
        # If push is sent, message wait for request approval
        # if push is not sent, message is sent by greenApi
        mobileNosToSkip = []
        if performOpenWindowCheck:
            for mobileNo in mobileNos:
                windowIsOpen = self.checkIf24HoursWindowIsOpen(mobileNo=mobileNo)
                if windowIsOpen == False:
                    lastOpenWindowMessageSent = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='openWindowMessageSent')
                    if not lastOpenWindowMessageSent: #12 hours
                        openWindowRefereeId = self.cacheService.resolveRefereeIdByMobile(mobileNo)
                        openWindowNotification = self.cacheService.getNotifications(tenantKey='GLOBAL', target='refereeGames', notificationType=NotificationTypeKey.openWindow, target_id=None, target_to=openWindowRefereeId, status='created')
                        if not openWindowNotification:
                            notification = {'contextDate': 'created', 'status': 'created'}
                            self.cacheService.setNotification(tenantKey='GLOBAL', target='refereeGames', notificationType=NotificationTypeKey.openWindow, target_id=None, target_to=openWindowRefereeId, value=notification)
                            mobileNosToSkip.append(mobileNo)
                        continue
                    elif (localNow - lastOpenWindowMessageSent).total_seconds() < 60 * 10: #10 minutes
                        sentPushMsgIds = self.sendPushNotification(to=mobileNo, title='מחכה לך הודעת ווטסאפ לאישור', body='הכנס/י אל הווטסאפ ולחץ על כפתור האישור')
                        mobileNosToSkip.append(mobileNo)
                        continue

        for mobileNo in mobileNos:
            if mobileNo in mobileNosToSkip:
                continue
            globalRefereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=mobileNo)
            sendMessagesToTelegram = globalRefereeDetail.get('telegramId') and globalRefereeDetail.get('sendMessagesToTelegram', False) or False
            windowIsOpen = self.checkIf24HoursWindowIsOpen(mobileNo=mobileNo)
            msgSidForMobile = None
            sentPushMsgIdsForMobile = []
            if skipPushNotification == False:
                urls = helpers.extract_urls(message)
                url = urls[0] if urls else None
                if internalMsgId:
                    sentPushMsgIdsForMobile = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', target=mobileNo, notificationType='push', target_id=internalMsgId, to=mobileNo, timestamp=0) or []
                if not sentPushMsgIdsForMobile:
                    sentPushMsgIdsForMobile = self.sendPushNotification(
                        to=mobileNo, title=title or 'הודעה נשלחה', body=message, url=url, section=pushSection,
                        gameId=gameId, category=pushCategory, leaveByTime=leaveByTime
                    )
                    if internalMsgId:
                        self.cacheService.setCacheOnlyKeyVal(tenantKey='GLOBAL', target=mobileNo, notificationType='push', target_id=internalMsgId, to=mobileNo, timestamp=0, value=sentPushMsgIdsForMobile, ttlSeconds=60 * 60 * 24)
                    sentPushMsgIds.extend(sentPushMsgIdsForMobile)
                    if sentPushMsgIdsForMobile:
                        self.setRefereeMessage(mobileNo=mobileNo, direction='TO', title=title, message=message, previewUrl=previewUrl, sendAt=helpers.localNow(), forceUseGreenApi=forceUseGreenApi, skipPushNotification=skipPushNotification, msgSid=sentPushMsgIdsForMobile[0], source='push')

            forceUseGreenApi = globalRefereeDetail.get('forceUseGreenApi') or False
            useGreenApi = False
            if self.useGreenApi and (forceUseGreenApi and self.checkSendGreenApiMessages(to=mobileNo) or forceUseGreenApi):
                useGreenApi = True
            else:
                failedMessageToMeta = self.cacheService.getCacheOnlyKeyVal(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='failedMessageToMeta')
                if failedMessageToMeta and failedMessageToMeta.get('errorCode') in [131026, 131000]:
                    useGreenApi = True

            if self.activeClient == 'greenApi' or useGreenApi:
                msgSidForMobile = await self.greenApiSendMessage(to=mobileNo, message=message, previewUrl=previewUrl)
                self.setRefereeMessage(mobileNo=mobileNo, direction='TO', title=title, message=message, previewUrl=previewUrl, sendAt=helpers.localNow(), forceUseGreenApi=forceUseGreenApi, skipPushNotification=skipPushNotification, msgSid=msgSidForMobile, source='greenapi')
            else:
                if windowIsOpen:
                    if msgSidForMobile == 'twilio':
                        msgSidForMobile = await self.useTwilioMessage(to=mobileNo, message=message, previewUrl=previewUrl)
                    elif self.activeClient == 'meta':
                        msgSidForMobile = self.metaClient.sendMessage(to=mobileNo, message=message, title=title, previewUrl=previewUrl, replyToMessageId=replyToMessageId)
                    elif self.activeClient == 'manychat':
                        msgSidForMobile = self.manychatClient.sendMessage(to=mobileNo, message=message, previewUrl=previewUrl)
                    self.setRefereeMessage(mobileNo=mobileNo, direction='TO', title=title, message=message, previewUrl=previewUrl, sendAt=helpers.localNow(), forceUseGreenApi=forceUseGreenApi, skipPushNotification=skipPushNotification, msgSid=msgSidForMobile, source=self.activeClient)
                    if sendMessagesToTelegram:
                        msgSidForMobile = self.telegramClient.sendMessage(chatId=globalRefereeDetail.get('telegramId'), mobileNo=mobileNo, message=message, title=title, previewUrl=previewUrl, replyToMessageId=replyToMessageId)
                        self.setRefereeMessage(mobileNo=mobileNo, direction='TO', title=title, message=message, previewUrl=previewUrl, sendAt=helpers.localNow(), forceUseGreenApi=forceUseGreenApi, skipPushNotification=skipPushNotification, msgSid=replyToMessageId, source='telegram')
                elif len(sentPushMsgIdsForMobile) == 0:
                    self.logger.warning(f'sendMessageToList to={mobileNo} Window is closed, using greenApi')
                    msgSidForMobile = await self.greenApiSendMessage(to=mobileNo, message=message, previewUrl=previewUrl)
                    self.setRefereeMessage(mobileNo=mobileNo, direction='TO', title=title, message=message, previewUrl=previewUrl, sendAt=helpers.localNow(), forceUseGreenApi=forceUseGreenApi, skipPushNotification=skipPushNotification, msgSid=msgSidForMobile, source='greenapi')

            if msgSidForMobile:
                msgLog = {
                    'origin': 'system',
                    'type': 'sendMessageToList',
                    'to': mobileNo,
                    'toName': globalRefereeDetail.get('name'),
                    'message': message,
                    'title': title,
                    'previewUrl': previewUrl,
                    'msgSid': msgSidForMobile,
                    'gameId': gameId,
                }
                self.msgLogger.info(msgLog)

            msgSid = msgSid or msgSidForMobile

        return msgSid, sentPushMsgIds

    async def sendMessage(self, to, message:str, title:str=None, previewUrl:bool=False, sendAt:str=None, forceUseGreenApi:bool=False, skipPushNotification:bool=False, replyToMessageId:str=None, performOpenWindowCheck:bool=False, returnSentPushMsgIds:bool=False, internalMsgId:str=None, gameId:str=None, pushSection:str=None, pushCategory:str=None, leaveByTime:str=None):
        msgSid = None
        sentPushMsgIds = []
        if self.useGreenApi and isinstance(to, dict) and to.get('chatGroupId'):
            msgSid = await self.greenApiSendMessage(to=to['chatGroupId'], message=message, previewUrl=previewUrl)
        else:
            (msgSid, sentPushMsgIds) = await self.sendMessageToList(
                to=to,
                message=message,
                title=title,
                previewUrl=previewUrl,
                forceUseGreenApi=forceUseGreenApi,
                skipPushNotification=skipPushNotification,
                performOpenWindowCheck=performOpenWindowCheck,
                internalMsgId=internalMsgId,
                gameId=gameId,
                pushSection=pushSection,
                pushCategory=pushCategory,
                leaveByTime=leaveByTime,
            )
        mobileNos = to['activeGroupMobileNumbers'] if isinstance(to, dict) and 'activeGroupMobileNumbers' in to else (to if isinstance(to, list) else [to])
        if msgSid and len(mobileNos) > 0:
            value = {
                'to': mobileNos,
                'message': message,
                'title': title,
                'previewUrl': previewUrl,
                'sendAt': sendAt,
                'forceUseGreenApi': forceUseGreenApi,
                'skipPushNotification': skipPushNotification,
                'activeClient': self.activeClient,
                'metaOutboundAttempt': 1,
            }
            self.cacheService.setMessage(msgSid=msgSid, value=value)
            #self.cacheService.setRefereeMessage(mobileNo=mobileNos[0], direction='TO', msgSid=msgSid, value=value)
        if sentPushMsgIds:
            for msgId in sentPushMsgIds:
                value = {
                    'to': mobileNos,
                    'message': message,
                    'title': title,
                    'activeClient': 'PushNotification'
                }
                self.cacheService.setMessage(msgSid=msgId, value=value)
        if returnSentPushMsgIds:
            return msgSid, sentPushMsgIds
        else:
            return msgSid

    async def sendLocation(self, to: str, latitude:str, longitude:str, name:str, address:str) -> dict:
        msgSid = None
        if self.useGreenApi and isinstance(to, dict) and 'chatGroupId' in to:
            msgSid = await self.greenApiSendLocation(to=to['chatGroupId'],latitude=latitude, longitude=longitude, name=name, address=address)
        elif self.useMeta:
            msgSid = self.metaClient.sendLocation(to=to, latitude=latitude, longitude=longitude, name=name, address=address, returnMsgSid=True)
        return msgSid

    async def sendPoll(self, to, message, options, extra=None, multipleAnswers=False, quotedMsgId=None):
        if self.useGreenApi:
            if isinstance(to, dict) and 'chatGroupId' in to:
                to = to['chatGroupId']
            return await self.greenApiClient.handleAction(action='sendPoll', payload={'to': to, 'message': message, 'options': options, 'extra': extra, 'multipleAnswers': multipleAnswers, 'quotedMsgId': quotedMsgId})
        return None
    
    async def getMessageTemplate(self, mobile, messageTemplate):
        try:
            messageFile = f'{ConfigManager.get_config_value(self.config, "MY_DATA_FOLDER", "/run/data/")}messageTemplates/{messageTemplate}'
            helpers.validatePath(messageFile)
            boto3s3 = boto3.client('s3')
            bucketName = helpers.getBucketName()
            s3Key = f'messageTemplates/{messageTemplate}'
            boto3s3.download_file(bucketName, s3Key, messageFile)

            with open(messageFile, 'r') as file:
                message = file.read().strip()
                return message
        except Exception as ex:
            self.logger.error(f'sendMessageTemplate {mobile} {bucketName} {s3Key} {messageTemplate}', ex)
        return None 

    def get_content_encoding(self, client_info=None):
        """Determine encoding based on client capabilities"""
        if not client_info or client_info.get('supports_aes128gcm'):
            return 'aes128gcm'
        else:
            return 'aesgcm'  # Fallback for older clients

    def get_vapid_audience_from_subscription(self, pushSubscription):
        """Extract audience from subscription endpoint"""
        try:
            # Parse the subscription endpoint to get the domain
            if isinstance(pushSubscription, str):
                self.logger.warning(f"get_vapid_audience_from_subscription pushSubscription is a string: {pushSubscription}")
                return None
            
            endpoint = pushSubscription.get('endpoint', '')
            parsed = urlparse(endpoint)
            
            # Build the audience URL
            audience = f"{parsed.scheme}://{parsed.netloc}"
            
            self.logger.debug(f"�� Detected audience: {audience}")
            return audience
            
        except Exception as ex:
            self.logger.error(f"⚠️ Could not parse audience from subscription:", ex)
            # Fallback to default
            return ConfigManager.get_config_value(self.config, 'PWA_BASE_URL')

    def sendPushNotification(self, to:str, title:str=None, body:str=None, url:str=None, tag:str=None, actions:list=None, requireInteraction:bool=True, silent:bool=False, vibrate:list=None, dir:str=None, lang:str=None, critical:bool=False, section:str=None, clientIdentifier:str=None, gameId:str=None, category:str=None, leaveByTime:str=None) -> list:# This is the user's subscription object, obtained from their browser
        # and stored in your database.
        refereeDetail = self.cacheService.getReferees(tenantKey='GLOBAL', mobileNo=to)
        if clientIdentifier:
            clientIdentifiers = [clientIdentifier]
        else:
            clientIdentifiers = refereeDetail.get('clientIdentifiers', [])
        if not clientIdentifiers:
            return []
            
        # Your VAPID keys
        vapid_private_key = self.vapidPrivateKey
        current_time = int(time.time())
        vapid_claims = {
            "sub": "mailto:admin@refereex.com",  # Your email
            "aud": ConfigManager.get_config_value(self.config, 'PWA_BASE_URL'),  # FCM audience
            "exp": current_time + 12 * 3600,  # Expires in 12 hours
            "iat": current_time               # Issued at
        }
        content_encoding=self.get_content_encoding()
        # The notification payload
        message_data = {
            "title": title or 'RefereeX',
            "body": body or 'הודעה3 חדשה מ-RefereeX',
            "timestamp": current_time,
            "url": url,
            "tag": tag or 'refereex-notification',
            "actions": actions,
            "requireInteraction": requireInteraction,
            "silent": silent,
            "vibrate": vibrate or [200, 100, 200],
            "critical": critical,
            "dir": dir or 'rtl',
            "lang": lang or 'he-IL'    
        }
        if section:
            message_data['section'] = section

        success_count = 0
        error_count = 0

        sentPushMsgIds = []
        for clientIdentifier in clientIdentifiers:
            value = self.cacheService.getClientIdentifier(clientIdentifier=clientIdentifier)
            if not value or not value.get('pushSubscription'):
                continue
            pushSubscription = value.get('pushSubscription')
            platform = value.get('platform')

            if platform == 'ios' and isinstance(pushSubscription, str) and pushSubscription not in ('EXPIRED_PUSH_SUBSCRIPTION', 'MISSING_PUSH_SUBSCRIPTION'):
                msgId = f'PN{str(uuid.uuid4())[:8]}'
                result = self.apnsClient.send(deviceToken=pushSubscription, title=title, body=body, gameId=gameId, section=section, category=category, leaveByTime=leaveByTime)
                if result.get('success'):
                    self.logger.info(f"APNs notification sent successfully {clientIdentifier}")
                    success_count += 1
                    sentPushMsgIds.append(msgId)
                    self.msgLogger.info({
                        'origin': 'system',
                        'type': 'sendPushNotification',
                        'to': to,
                        'toName': refereeDetail.get('name'),
                        'clientIdentifier': clientIdentifier,
                        'pushSubscription': pushSubscription,
                        'title': title,
                        'body': body,
                        'url': url,
                        'msgId': msgId,
                        'gameId': gameId,
                    })
                else:
                    self.logger.warning(f"❌ APNs error for {clientIdentifier}")
                    if result.get('expired'):
                        self.cacheService.setClientIdentifier(clientIdentifier=clientIdentifier, sessionIdentifier=value.get('sessionIdentifier'), pushSubscription='EXPIRED_PUSH_SUBSCRIPTION')
                    error_count += 1
                continue

            if not pushSubscription or isinstance(pushSubscription, str):
                continue
            userAgent = value.get('userAgent')

            vapid_audience = self.get_vapid_audience_from_subscription(pushSubscription=pushSubscription)
            vapid_claims['aud'] = vapid_audience

            try:
                msgId = f'PN{str(uuid.uuid4())[:8]}'
                message_data['msgId'] = msgId
                response = webpush(
                    subscription_info=pushSubscription,
                    data=json.dumps(message_data),
                    vapid_private_key=vapid_private_key,
                    vapid_claims=vapid_claims,
                    content_encoding=content_encoding,
                    headers={}
                )
                self.logger.info(f"Notification sent successfully {clientIdentifier}, status code:{response.status_code}")
                success_count += 1
                sentPushMsgIds.append(msgId)

                msgLog = {
                    'origin': 'system',
                    'type': 'sendPushNotification',
                    'to': to,
                    'toName': refereeDetail.get('name'),
                    'clientIdentifier': clientIdentifier,
                    'pushSubscription': pushSubscription,
                    'title': title,
                    'body': body,
                    'url': url,
                    'msgId': msgId,
                    'gameId': gameId,
                }
                self.msgLogger.info(msgLog)
            
            except WebPushException as ex:
                self.logger.warning(f"❌ WebPush error for {clientIdentifier}:", ex)
                if hasattr(ex, 'response') and ex.response is not None:
                    self.logger.warning(f"  Status: {ex.response.status_code}, Body: {ex.response.text}")
                    if ex.response.status_code == 410:
                        self.cacheService.setClientIdentifier(clientIdentifier=clientIdentifier, sessionIdentifier=value.get('sessionIdentifier'), pushSubscription='EXPIRED_PUSH_SUBSCRIPTION')
                error_count += 1
            except Exception as ex:
                self.logger.error(f"❌ General error for {clientIdentifier}:", ex)
                error_count += 1
        
        return sentPushMsgIds

    def broadcastPwaRefreshPushNotification(
        self,
        title: str = None,
        body: str = None,
        max_age_days: int = 365,
    ) -> dict:
        """
        Send a Web Push to all client identifiers with a valid subscription (recently registered).
        Payload includes pwaRefresh=true; the service worker opens the PWA and triggers reload / skipWaiting.
        """
        vapid_private_key = self.vapidPrivateKey
        current_time = int(time.time())
        tag = f'pwa-refresh-{current_time}'
        content_encoding = self.get_content_encoding()
        base_vapid_claims = {
            'sub': 'mailto:admin@refereex.com',
            'aud': ConfigManager.get_config_value(self.config, 'PWA_BASE_URL'),
            'exp': current_time + 12 * 3600,
            'iat': current_time,
        }
        from_dt = helpers.localNow() - timedelta(days=max(1, int(max_age_days or 365)))
        rows = self.cacheService.getClientIdentifier(clientIdentifier=None, from_created=from_dt) or {}
        if not isinstance(rows, dict):
            return {'sent': 0, 'failed': 0, 'skipped': 0, 'candidates': 0}

        sent = 0
        failed = 0
        skipped = 0
        candidates = 0

        for client_id, row in rows.items():
            if not isinstance(row, dict):
                continue
            push_subscription = row.get('pushSubscription')
            mobile_no = row.get('mobileNo')
            if not push_subscription or isinstance(push_subscription, str):
                skipped += 1
                continue
            if push_subscription in ('EXPIRED_PUSH_SUBSCRIPTION', 'MISSING_PUSH_SUBSCRIPTION'):
                skipped += 1
                continue
            if mobile_no == 'XX':
                skipped += 1
                continue
            candidates += 1
            vapid_claims = dict(base_vapid_claims)
            vapid_audience = self.get_vapid_audience_from_subscription(pushSubscription=push_subscription)
            vapid_claims['aud'] = vapid_audience

            msg_id = f'PN{str(uuid.uuid4())[:8]}'
            message_data = {
                'title': title or 'עדכון RefereeX',
                'body': body or 'גרסה חדשה פורסמה. לחץ לרענון האפליקציה.',
                'timestamp': current_time,
                'tag': tag,
                'pwaRefresh': True,
                'requireInteraction': True,
                'silent': False,
                'vibrate': [200, 100, 200],
                'critical': False,
                'dir': 'rtl',
                'lang': 'he-IL',
                'msgId': msg_id,
            }

            try:
                webpush(
                    subscription_info=push_subscription,
                    data=json.dumps(message_data),
                    vapid_private_key=vapid_private_key,
                    vapid_claims=vapid_claims,
                    content_encoding=content_encoding,
                    headers={},
                )
                sent += 1
                self.msgLogger.info(
                    {
                        'origin': 'system',
                        'type': 'broadcastPwaRefreshPushNotification',
                        'clientIdentifier': client_id,
                        'mobileNo': mobile_no,
                        'msgId': msg_id,
                    }
                )
            except WebPushException as ex:
                self.logger.warning(f'❌ WebPush broadcast error for {client_id}:', ex)
                if hasattr(ex, 'response') and ex.response is not None and ex.response.status_code == 410:
                    self.cacheService.setClientIdentifier(
                        clientIdentifier=client_id,
                        sessionIdentifier=row.get('sessionIdentifier'),
                        pushSubscription='EXPIRED_PUSH_SUBSCRIPTION',
                    )
                failed += 1
            except Exception as ex:
                self.logger.error(f'❌ Broadcast push error for {client_id}:', ex)
                failed += 1

        self.logger.info(
            f'broadcastPwaRefreshPushNotification: sent={sent} failed={failed} skipped={skipped} candidates={candidates}'
        )
        return {
            'sent': sent,
            'failed': failed,
            'skipped': skipped,
            'candidates': candidates,
            'tag': tag,
        }

    def validatePushSubscription(self, pushSubscription: any) -> dict:
        """
        Validate if a push subscription is still valid by attempting to send a test notification.
        
        Args:
            pushSubscription: The push subscription object to validate
            
        Returns:
            dict: {
                'valid': bool,
                'expired': bool,
                'error': str or None,
                'status_code': int or None
            }
        """
        if not pushSubscription or pushSubscription == 'EXPIRED_PUSH_SUBSCRIPTION' or pushSubscription == 'MISSING_PUSH_SUBSCRIPTION':
            return {
                'valid': False,
                'expired': True,
                'error': 'Invalid or missing subscription',
                'status_code': None
            }
        
        try:
            # Get VAPID configuration
            vapid_private_key = self.vapidPrivateKey
            current_time = int(time.time())
            vapid_audience = self.get_vapid_audience_from_subscription(pushSubscription=pushSubscription)
            
            vapid_claims = {
                "sub": "mailto:admin@refereex.com",
                "aud": vapid_audience,
                "exp": current_time + 12 * 3600,
                "iat": current_time
            }
            
            content_encoding = self.get_content_encoding()
            
            # Send a silent test notification to validate the subscription
            # Using minimal data to avoid showing a notification to the user
            test_message_data = {
                "title": "",
                "body": "",
                "silent": True,
                "tag": "subscription-validation",
                "timestamp": current_time
            }
            
            # Attempt to send the test notification
            response = webpush(
                subscription_info=pushSubscription,
                data=json.dumps(test_message_data),
                vapid_private_key=vapid_private_key,
                vapid_claims=vapid_claims,
                content_encoding=content_encoding,
                headers={}
            )
            
            # If we get here without exception, subscription is valid
            return {
                'valid': True,
                'expired': False,
                'error': None,
                'status_code': response.status_code if hasattr(response, 'status_code') else 200
            }
            
        except WebPushException as ex:
            # Check if it's an expiration error (410 Gone)
            status_code = None
            if hasattr(ex, 'response') and ex.response is not None:
                status_code = ex.response.status_code
                
            is_expired = (status_code == 410)
            
            return {
                'valid': False,
                'expired': is_expired,
                'error': str(ex),
                'status_code': status_code
            }
            
        except Exception as ex:
            # Other errors (network, invalid format, etc.)
            return {
                'valid': False,
                'expired': False,
                'error': str(ex),
                'status_code': None
            }

    async def checkWhatsapp(self, mobileNo):
        if False and self.useGreenApi:
            checkWhatsapp = await self.greenApiClient.handleAction(action='checkWhatsapp', payload={'mobileNo': mobileNo})
            return checkWhatsapp.get('existsWhatsapp')
        else:
            mobileNo = _adjustMobileNo(mobileNo=mobileNo)
            lookups = self.twilioClient.lookups(mobileNo)
            return lookups is not None

    async def sendNewGameNotificationForWaiting(self, referees):
        title = '*שיבוץ חדש*'
        for refId, refereeDetail in referees.items():
            games = self.cacheService.getRefereeGames(refereeId=refereeDetail.get('refereeId'), refId=refId)
            for gamePk, refereeGame in games.items():
                if refereeGame['status'] != 'מאושר':
                    title = '*שיבוץ מחכה לאישור*'
                    msgSid, sentPushMsgIds = await self.sendNewGameNotification(refereeGame=refereeGame, title=title, refId=refId, toMobile=refereeDetail["mobileNo"], toName=refereeDetail["name"])
                    refereeGame['newMessageSid'] = msgSid
                    refereeGame['newPushMsgIds'] = sentPushMsgIds
                    self.cacheService.setRefereeGame(refereeId=refereeDetail.get('refereeId'), refId=refId, gamePk=gamePk, value=refereeGame)

    def sendInteractiveMessage(self, to: str, question: str, promptButtons: dict, interactiveType: str='button', customData: dict={}, header=None, replyToMessageId=None, sendAt=None):
        msgSid = self.metaClient.sendInteractiveMessageWrapper(toMobile=to, question=question, promptButtons=promptButtons, interactiveType=interactiveType, header=header, replyToMessageId=replyToMessageId, sendAt=sendAt)
        if msgSid and customData:
            self.cacheService.setReferenceId(target='msgSid', target_id=msgSid, value=customData)
        return msgSid

    async def sendBotContact(self, to):
        if self.useMeta:
            self.metaClient.sendBotContact(to=to)
        
        if self.useGreenApi:
            chatId = self.greenApiClient.getChatId(to)
            contact = {
                "phoneContact": self.greenApiClient.cleanMobileNo(self.greenApiClient.fromMobile), 
                "company": "שירות עדכונים והתראות לשופטים"
            }
            await self.greenApiClient.handleAction('sendContact', {'to': chatId, 'contact': contact})

    async def getContactInfo(self, to):
        if self.useGreenApi:
            mobileDetails = await self.greenApiClient.handleAction('getContactInfo', {'to': to})
            return mobileDetails
        else:
            return {}
    
    async def updateGroupParticipants(self, gameDetail):
        REVIEWER_ROLE = 'מבקר'
        chatGroupId = gameDetail.get('chatGroupId')
        groupName = gameDetail.get('groupName')
        referees = gameDetail.get('referees', {})
        refereesMobileNosNames = {}
        if self.addNonActiveRefereesToGroups:
            refereesMobileNosNames = { refDetail['* phone']: refDetail['* name'] for refDetail in referees if refDetail['role'] != REVIEWER_ROLE }
        else:
            refereesMobileNosNames = { refDetail['* phone']: refDetail['* name'] for refDetail in referees if refDetail['role'] != REVIEWER_ROLE and refDetail['* phone'] in gameDetail['activeGroupMobileNumbers'] }
        
        groupData = await self.greenApiClient.handleAction('getGroupData', {'chatGroupId': chatGroupId}) 
        if isinstance(groupData, dict):
            prevGroupParticipantIds = [ participant['id'] for participant in groupData['participants'] ]
            prevGroupParticipantIds.remove(self.greenApiFromChatId)
            currentGroupParticipants = {}
            for mobileNo, refName in refereesMobileNosNames.items():
                chatId = self.greenApiClient.getChatId(mobileNo)
                currentGroupParticipants[chatId] = refName
            removedParticipantIds = list(set(prevGroupParticipantIds) - set(currentGroupParticipants.keys()))
            addedParticipantIds = list(set(currentGroupParticipants.keys()) - set(prevGroupParticipantIds))

            for chatId in removedParticipantIds:
                #continue
                response = await self.greenApiClient.handleAction('removeGroupParticipant', {'chatGroupId': chatGroupId, 'to': chatId})

            for chatId in addedParticipantIds:
                #continue
                response = await self.greenApiClient.handleAction('addGroupParticipant', {'chatGroupId': chatGroupId, 'to': chatId})
                if response.get('addParticipant', False) == False:
                    mobileNo = self.greenApiClient.getMobileNo(chatId=chatId)
                    addedRefereeTenantDetails = self.cacheService.getReferees(tenantKey=gameDetail['tenantKey'], mobileNo=mobileNo)
                    if not addedRefereeTenantDetails or addedRefereeTenantDetails.get('status') != 'active':
                        noticeTitle = f'*הצטרפת לקבוצה*'
                        noticeDetails = f'אהלן, שובצת למשחק {gameDetail["gameTitle"]}, לצרכי המשחק נפתחה קבוצת WhatsApp שאליה ניתן להצטרף על ידי הקישור הבא: {groupData["groupInviteLink"]}'
                        #noticeDetails = f'ניתן להצטרף לקבוצה של המשחק {gameDetail["tenantKey"]}-{gameDetail["tournamentName"]}-{gameDetail["gameTitle"]} באמצעות הקישור הבא: {gameDetail["groupInviteLink"]}'
                        msgSid = await self.greenApiSendMessage(to=mobileNo, message=f'{noticeTitle}\n{noticeDetails}', previewUrl=False)
                    else:
                        notification = {'contextDate': 'created', 'status': 'created'}
                        self.cacheService.setNotification(tenantKey=gameDetail['tenantKey'], target='refereeGames', target_id=gameDetail.get('id') or gameDetail['gamePk'], notificationType=NotificationTypeKey.joinChatGroup, target_to=chatId, value=notification)

            if False and len(groupData['participants']) < len(referees):
                message = f'אהלן {currentGroupParticipants[chatId]}, שובצת למשחק {groupName}, לצרכי המשחק נפתחה קבוצת WhatsApp שאליה ניתן להצטרף על ידי הקישור הבא: {groupData["groupInviteLink"]}'
                if recentJoinConfirmationReply:
                    message = f'{message}\n\nבנוסף, בבקשה לשמור בנייד את איש הקשר הנ״ל לשיבוצים הבאים'
                await self.sendMessage(to=chatId, message=message)

    def getWhatsAppUrl(self, text):
        encodedText = urllib.parse.quote(text)
        if self.activeClient == 'greenApi':
            botMobile = self.greenApiClient.fromMobile
        elif self.activeClient == 'twilio':
            botMobile = self.twilioClient.fromMobile
        elif self.activeClient == 'meta':
            botMobile = self.metaClient.fromMobile
        elif self.activeClient == 'manychat':
            botMobile = self.manychatClient.fromMobile
    
        url = ConfigManager.get_config_value(self.config, 'whatsappUrlBase').format(botMobile, encodedText)
        return url

    async def twilioIncomingWebhookAsync(self, incomingWebhookCallback, alwaysSendMessage, request: Request):
        return await self.twilioClient.handleIncomingWebhook(incomingWebhookCallback=incomingWebhookCallback, alwaysSendMessage=alwaysSendMessage, request=request)
    
    def twilioIncomingWebhook(self, incomingWebhookCallback, alwaysSendMessage, request: Request):
        asyncio.create_task(self.twilioIncomingWebhookAsync(incomingWebhookCallback=incomingWebhookCallback, alwaysSendMessage=alwaysSendMessage, request=request))

    async def greenApiIncomingWebhook(self, incomingWebhookCallback, request: Request):
        return await self.greenApiClient.handleIncomingWebhook(incomingWebhookCallback=incomingWebhookCallback, request=request)

    async def manychatIncomingWebhook(self, incomingWebhookCallback, request: Request):
        return await self.manychatClient.handleIncomingWebhook(incomingWebhookCallback=incomingWebhookCallback, request=request)

    async def metaIncomingWebhook(self, incomingWebhookCallback, request: Request):
        return await self.metaClient.handleIncomingWebhook(incomingWebhookCallback=incomingWebhookCallback, request=request, alwaysSendMessage=True)

    async def telegramIncomingWebhook(self, incomingWebhookCallback, request: Request):
        if not self.useTelegram:
            return {"status": "telegram_not_configured"}, 503, "application/json"
        return await self.telegramClient.handleIncomingWebhook(incomingWebhookCallback=incomingWebhookCallback, alwaysSendMessage=True, request=request)

    async def sendEmail(self, recipients, subject, body, attachment=None, fromName=None):
        try:
            if fromName is None:
                fromName = ConfigManager.get_config_value(self.config, 'brevoSenderName')
            else:
                fromName = ConfigManager.get_config_value(self.config, 'brevoSenderName') + ' בשם ' + fromName

            payload = {
                "sender": {
                    "name": fromName,
                    "email": ConfigManager.get_config_value(self.config, 'brevoSenderEmail')
                },
                "to": recipients,
                "subject": subject
            }

            if body:
                payload['htmlContent'] = body

            if attachment:
                payload['attachment'] = attachment

            data = json.dumps(payload)

            headers = {
                'accept': 'application/json',
                'api-key': self.brevoApiKey,
                'content-type': 'application/json'
            }

            response = requests.request("POST", self.brevoApiUrl, headers=headers, data=data)
            
            # Debug response
            self.logger.info(f'Brevo API response status: {response.status_code}')
            self.logger.info(f'Brevo API response: {response.text}')
            
            if response.status_code == 201:
                messageId = response.json().get('messageId')
                return messageId
            else:
                self.logger.error(f'Brevo API error: {response.status_code} - {response.text}')
                return None

        except Exception as ex:
            self.logger.error(f"❌ General error for {subject}:", ex)
            return None

    async def test(self):
        message = 'test'
        await self.sendMessage(to='972547799979', message=message)
        message = f'{message}\nhttps://testtwilio.requestcatcher.com/test'
        await self.sendMessage(to='972547799979', message=message)
        message1 = message.replace("://", ":​//")
        await self.sendMessage(to='972547799979', message=message1)

if __name__ == '__main__':
    a = os.getenv('metaOpenWindowMessageTemplate')
    font = os.getenv('fontPath')
    print(f'font {font}')
    from shared.appContainer import AppContainer
    import shared.configurationDI as configDI
    container = AppContainer()
    container.config.from_dict(configDI.configDI)
    container.init_resources()

    #service = MessagingService(logger=logging.getLogger(), cacheService=cacheService, refereesByMobile={'+972547799979': {'name': 'Guy', 'mobileNo': '+972547799979'}}, activeClient='meta', metaClient=MetaClient(logger=logging.getLogger(), cacheService=cacheService, fromMobile='+972547799979', useClient=True, apiVersion='v24.0', fromPhoneNumberId='120702945000013', whatsappBusinessAccountId='120702945000013'))
    service = container.messaging_service()
    cacheService = container.cache_service()
    #msgSid = service.sendPushNotification(to='+972547799979', title='test title', body='test body', clientIdentifier='732E0E17-B650-4283-97F8-F300958D647B')
    #failedMessageToMeta = cacheService.getCachedKeyVal(tenantKey='GLOBAL', mobileNo='+972547799979', propertyName='failedMessageToMeta')
    #print(failedMessageToMeta)
    exit(0)
    gameDetail = cacheService.get_tournament_game_by_pk(tenantKey='IL#football#2025-26', tournamentName='ליגת נערים ב\' מרכז', gamePk='ליגת נערים ב\' מרכזמ.ס. איחוד דרום השרון "צו פיוס"  מכבי השקמה חן צפון "צו פיוס"22')
    print(gameDetail)
    msgSid = asyncio.run(service.sendMessage(to=gameDetail, message='test message', title='test title'))
    print(msgSid)
    exit(0)
    #service.msgLogger.info(f'test starts...')
    cacheService = container.cache_service()
    handleRefereeData = container.handle_referee_data()
    pendingRefereeGames = handleRefereeData.getPendingRefereeGames()

    gameDetail = cacheService.getGameDetailById('226e72eb')
    asyncio.run(service.sendNewGameNotification(refereeGame=gameDetail, title='*שיבוץ חדש*', refId='43679', toMobile='+972547799979', toName='Guy', sendAt=None, skipPushNotification=False))
    exit(0)

    isOpen1 = service.checkIf24HoursWindowIsOpen(mobileNo='+972522652277')
    isOpen2 = service.checkIf24HoursWindowIsOpen(mobileNo='+972546402507')
    isOpen3 = service.checkIf24HoursWindowIsOpen(mobileNo='+972502686250')
    msgSid1 = asyncio.run(service.sendOpenWindowMessage(toMobile='+972547799979', toName='ליאן'))
    msgSid2 = asyncio.run(service.sendOpenWindowMessage(toMobile='+972546402507', toName='יונתן'))
    msgSid3 = asyncio.run(service.sendOpenWindowMessage(toMobile='+972502686250', toName='גרין'))
    print(isOpen1)
    print(isOpen2)
    print(isOpen3)
    print(msgSid1)
    print(msgSid2)
    print(msgSid3)
    pass

    msgSid = asyncio.run(service.sendMessage(to='+972547799979', message='test message', title='test title', returnSentPushMsgIds=False))
    while True:
        clientIdentifier = '233e1f9f-5c78-49e0-8661-bf793a293dc2'
        clientIdentifier = '4d90d875-338f-4751-818d-ffb035b5f423'
        clientIdentifier = '9fa26a05-a694-4876-8e8f-5d1deea2265c'
        clientIdentifier = None
        sentPushMsgIds = service.sendPushNotification(to='+972547799979', title='test title', body='test body', url='', requireInteraction=True, critical=False, clientIdentifier=clientIdentifier)
        print(sentPushMsgIds)
        msgSid = asyncio.run(service.sendMessage(to='+972547799979', message='test message', title='test title', returnSentPushMsgIds=False))
        print(msgSid)
        msgSid, sentPushMsgIds = asyncio.run(service.sendMessage(to='+972547799979', message='test message', title='test title', returnSentPushMsgIds=True))
        print(msgSid)
        print(sentPushMsgIds)
        time.sleep(5)
    exit(0)
    gameDetail = container.db_client().getGameDetailById('226e72eb')
    #asyncio.run(service.sendNewGameNotificationForWaiting(referees={'43679': {'name': 'Guy', 'mobileNo': '+972547799979'}}))
    attachmentJson = {'name': 'test.json', 'content': 'test content'}
    import base64
    attachmentBase64 = base64.b64encode(json.dumps(attachmentJson).encode('utf-8')).decode('utf-8')
    messageId = asyncio.run(service.sendEmail(recipients=[{'name':'Guy', 'email':'guyshachar.acc@gmail.com'}], subject='test subject', body='<html><body><p>Please find the attached document.</p></body></html>', attachment=[{'name': 'test.txt', 'content': attachmentBase64, 'contentType': 'application/jsdt'}]))
    print(messageId)

    service.sendPushNotification(to='+972547799979', title='test title', body='test body', url='https://refereex.com', critical=False)
    msgSid = asyncio.run(service.sendMessage(to='+972547799979', message='test message'))
    print(msgSid)
    #northUrl = service.getWhatsAppUrl('צפון')
    pass
    #checkWhatsapp = asyncio.run(service.checkWhatsapp('972547799979'))
    #gamePk = "ליגת נערים א' עלהפ' י-ם אורי נתן - הפועל רעננה29"
    #response = asyncio.run(service.updateGroupParticipants(gameDetail))#chatGroupId=gameDetail['chatGroupId'], groupName=gameDetail['groupName'], groupMobileNumbers=gameDetail['groupMobileNumbers']))
    #response = service.greenApiClient.addGroupParticipant(chatGroupId=gameDetail['chatGroupId'], to='972547799979')
    #response = asyncio.run(service.test())
    pass

# User-Initiated/Service Conversation is when the business receive a message from the user and it always reset 24 hours window that allow me to send free text messages
# Business-Initiated Conversation is when the business send a template message to the user when the 24 hours window is closed
#Conversation Category	Price per Conversation (USD)
#Marketing	~$0.0762
#Utility	~$0.0319
#Service (User-Initiated)	~$0.0127
#30 conversation days per referee = 0.0319 * 30 = 1$
#1000 first conversations for free = (30 * 400 - 1000) * 0.0319 = $350 a month
#8 months = 2800$