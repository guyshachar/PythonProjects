from datetime import datetime, timezone, timedelta
import time
import asyncio
import os
import sys
from whatsapp_api_client_python import API
import requests
import urllib3
import logging
import re
import functools
from fastapi import Request, HTTPException
from urllib.parse import urlparse, unquote, quote
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.rateLimitManager import RateLimitManager
from shared.logger import Logger
from shared.db import CacheService
from shared.messaging.messagingClientBase import MessagingClientBase  

class GreenApiClient(MessagingClientBase):
    def __init__(self, logger:Logger, cacheService:CacheService, greenApiInstanceId=None, fromMobile:str=None, useClient:bool=False):
        try:
            super().__init__(logger=logger, cacheService=cacheService, clientName='greenApi', fromMobile=fromMobile, useClient=useClient)
            self.logger = logger
            self.greenApiLogger = logger

            self.cacheService = cacheService
            self.incomingApiGuid = helpers.get_secret('incoming_api_guid')

            self.greenApi_instance_id = greenApiInstanceId
            self.greenApi_auth_token = helpers.get_secret('greenApi_auth_token')
            self.greenAPI = API.GreenAPI(self.greenApi_instance_id, self.greenApi_auth_token)
            self.useGreenApiMessages = os.getenv('useGreenApiMessages')
            self.greenApiSupportWhatsapp = os.getenv('greenApiSupportWhatsapp')

            self.greenApiUrlBase = os.getenv('greenApiUrlBase')

            # RefAlert webhook forwards (group messages). Full URLs; override if host/cert differs.
            self.refalertWebhookUrlTest = os.getenv(
                'REFALERT_WEBHOOK_URL_TEST',
                'https://refalert_test.refereex.com/api/webhook',
            ).strip()
            self.refalertWebhookUrlProd = os.getenv(
                'REFALERT_WEBHOOK_URL_PROD',
                'https://refalert.refereex.com/api/webhook',
            ).strip()
            # If cert does not match hostname (e.g. test subdomain), set REFALERT_WEBHOOK_VERIFY_SSL=0 — fix cert in production.
            _verify = os.getenv('REFALERT_WEBHOOK_VERIFY_SSL', '1').strip().lower()
            self.refalertWebhookVerifySsl = _verify in ('1', 'true', 'yes', 'on')
            self.logger.info(f"RefPortal webhook verify SSL: {self.refalertWebhookVerifySsl}")
            if not self.refalertWebhookVerifySsl:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            self.accountSettings = None
            try:
                self.accountSettings = self.getAccountSettings()
                self.greenApiBearerToken = self.accountSettings['webhookUrlToken']
            except Exception as ex:
                pass

            self.chatGroupsToForward = os.getenv('chatGroupsToForward', '').split(',')
            
            # Define per-action rate limits
            rateLimits = {
                "sendMessage": (50, 1),
                "sendButtons": (50, 1),
                "sendLocation": (50, 1),
                "sendContact": (50, 1),
                "sendPoll": (50, 1),
                "sendFileByUrl": (50, 1),
                "sendInteractiveButtons": (50, 1),
                "sendInteractiveButtonsReply": (50, 1),
                "createGroup": (1, 1),
                "updateGroupName": (1, 1),
                "getGroupData": (1, 1),
                "addGroupParticipant": (10, 1),
                "removeGroupParticipant": (10, 1),
                "leaveGroup": (10, 1),
                "setGroupPicture": (1, 1),
                "setGroupAdmin": (10, 1),
                "checkWhatsapp": (10, 1),
                "archiveChat": (10, 1),
                "getContactInfo": (1, 1),
                "getStateInstance": (1, 1)
            }
            self.rateLimitManager = RateLimitManager(logger=self.greenApiLogger, rateLimits=rateLimits, db_client=self.cacheService.dbClient)
        finally:
            pass
        
    def genericApi(self, action, payload, method='POST'):
        url = f"{self.greenApiUrlBase}waInstance{self.greenApi_instance_id}/{action}/{self.greenApi_auth_token}"

        headers = {
            'Content-Type': 'application/json'
        }

        response = None
        if method == 'POST':
            response = requests.post(url, json=payload)
        elif method == 'GET':
            url += '?'
            for param, value in payload.items():
                url += f'{param}={value}&'
            response = requests.get(url, params=payload)
        self.greenApiLogger.info(response.text.encode('utf8'))

        return response

    def getChatId(self, to):
        if not to:
            return None
        if to.endswith("@g.us"):
            chatId = to
        elif to.endswith("@c.us"):
            chatId = to
        else:
            chatId = f'{self.adjustMobileNo(to)}@c.us'
        return chatId

    def getMobileNo(self, chatId):
        mobileNo = f'+{self.cleanMobileNo(chatId)}'
        return mobileNo

    def getChatIds(self, tos):
        chatIds = [ self.getChatId(to) for to in tos ]
        return chatIds

    def clean_number_string(self, s):
        # Remove any invisible characters
        s = re.sub(r'[\u202a\u202c\u200e\u200f\xa0\u2066\u2067\u2068\u2069]', '', s)
        # Replace non-standard hyphens with normal ones
        s = s.replace('‑', '-')  # Unicode hyphen to normal hyphen
        # Remove hyphens/spaces if you want pure digits
        s = re.sub(r'[^0-9]', '', s)
        return s

    def adjustMobileNo(self, mobileNo):
        mobileNo = self.clean_number_string(mobileNo)
        mobileNo = mobileNo.replace(' ','').replace('-','').replace('+','').replace('‑','').replace('@c.us','')
        if len(mobileNo) == 10:
            mobileNo = f'972{mobileNo[1:]}'
        return mobileNo

    def getMobileChatId(self, mobileNo):
        if mobileNo.endswith("@c.us"):
            chatId = mobileNo
        else:
            chatId = f'{self.adjustMobileNo(mobileNo)}@c.us'
        return chatId

    def getStateInstance(self):
        response = self.greenAPI.account.getStateInstance()
        return response.data

    def rebootInstance(self):
        response = self.greenAPI.account.reboot()
        return response.data

    def getAccountSettings(self):
        response = self.greenAPI.account.getSettings()
        return response.data

    def checkWhatsapp(self, mobileNo):
        adjustedMobileNo = self.adjustMobileNo(mobileNo)
        response = self.greenAPI.serviceMethods.checkWhatsapp(phoneNumber=int(adjustedMobileNo))
        return response.data

    def getAvatar(self, to):
        chatId = self.getChatId(to)
        response = self.greenAPI.serviceMethods.getAvatar(chatId=chatId)
        return response.data

    def getGroupData(self, chatGroupId):
        chatId = self.getChatId(chatGroupId)
        response = self.greenAPI.groups.getGroupData(
            groupId=chatGroupId
        )
        return response.data

    def createGroup(self, groupName, tos=None):
        chatIds = self.getChatIds(tos)
        response = self.greenAPI.groups.createGroup(
            groupName=groupName, chatIds=chatIds
        )
        return response.data

    def updateGroupName(self, chatGroupId, groupName):
        response = self.greenAPI.groups.updateGroupName(
            groupId=chatGroupId, groupName=groupName
        )
        return response.data

    def addGroupParticipant(self, chatGroupId, to):
        chatId = self.getChatId(to)
        response = self.greenAPI.groups.addGroupParticipant(
            groupId=chatGroupId, participantChatId=chatId
        )
        return response.data

    def removeGroupParticipant(self, chatGroupId, to):
        chatId = self.getChatId(to)
        response = self.greenAPI.groups.removeGroupParticipant(
            groupId=chatGroupId, participantChatId=chatId
        )
        return response.data

    def setGroupPicture(self, chatGroupId, pictureFile):
        response = self.greenAPI.groups.setGroupPicture(
            groupId=chatGroupId, path=pictureFile 
        )
        return response.data

    def setGroupAdmin(self, chatGroupId, to):
        chatId = self.getChatId(to)
        response = self.greenAPI.groups.setGroupAdmin(
            groupId=chatGroupId, participantChatId=chatId
        )
        return response.data

    def archiveChat(self, to):
        chatId = self.getChatId(to)
        response = self.greenAPI.serviceMethods.archiveChat(
            chatId=chatId
        )
        return response.data
    
    def getContactInfo(self, to):
        chatId = self.getChatId(to)
        response = self.greenAPI.serviceMethods.getContactInfo(chatId=chatId)
        return response.data

    def getContacts(self, group:bool=None, count:int=None):
        payload = {}
        if group is not None:
            payload['group'] = 'true' if group else 'false'
        if count is not None:
            payload['count'] = count
        response = self.genericApi(action='getContacts', payload=payload, method='GET')
        data = jsonHelper.load_from_json(response.text)
        return data

    def sendMessage(self, to, message, mediaUrl=None, sendAt=None, quotedMessageId=None, previewUrl=False):
        chatId = self.getChatId(to)
        if not chatId:
            return None
        response = self.greenAPI.sending.sendMessage(chatId=chatId, message=message, quotedMessageId=quotedMessageId, linkPreview=previewUrl)
        msgSid = response.data.get('idMessage') if response.data else None
        return msgSid

    def sendInteractiveButtons(self, to, header, body=None, footer=None, buttons=None, previewUrl=False):
        chatId = self.getChatId(to)
        payload = {}
        payload['chatId'] = chatId
        if header:
            payload['header'] = header
        if body:
            payload['body'] = body
        if footer:
            payload['footer'] = footer
        if buttons:
            payload['buttons'] = buttons
        response = self.genericApi(action='sendInteractiveButtons', payload=payload, method='POST')
        data = jsonHelper.load_from_json(response.text)
        msgSid = data.get('idMessage') if data else None
        return msgSid

    def sendInteractiveButtonsReply(self, to, header, body=None, footer=None, buttons=None, linkPreview=False):
        chatId = self.getChatId(to)
        payload = {}
        payload['chatId'] = chatId
        if header:
            payload['header'] = header
        if body:
            payload['body'] = body
        if footer:
            payload['footer'] = footer
        if buttons:
            payload['buttons'] = buttons
        response = self.genericApi(action='sendInteractiveButtonsReply', payload=payload, method='POST')
        data = jsonHelper.load_from_json(response.text)
        msgSid = data.get('idMessage') if data else None
        return msgSid

    def sendContact(self, to, contact):
        chatId = self.getChatId(to)
        response = self.greenAPI.sending.sendContact(chatId=chatId, contact=contact)
        msgSid = response.data.get('idMessage') if response.data else None
        return msgSid

    def sendLocation(self, to, latitude, longitude, name, address, quotedMessageId=None):
        chatId = self.getChatId(to)
        response = self.greenAPI.sending.sendLocation(chatId=chatId, latitude=latitude, longitude=longitude, nameLocation=name, address=address, quotedMessageId=quotedMessageId)
        msgSid = response.data.get('idMessage') if response.data else None
        return msgSid

    def sendPoll(self, to, message, options, extra, multipleAnswers=False, quotedMsgId=None):
        chatId = self.getChatId(to)
        optionsDic = [{'optionName': option} for option in options]
        response = self.greenAPI.sending.sendPoll(chatId=chatId, message=message, options=optionsDic, multipleAnswers=multipleAnswers, quotedMessageId=quotedMsgId)
        msgSid = response.data.get('idMessage') if response.data else None
        if msgSid:
            self.cacheService.setMessage(msgSid, 
                {
                    'from': f'whatsapp:{self.fromMobile}',
                    'to': f'whatsapp:{to}',
                    'message': message,
                    'extra': extra,
                    'type': 'sendPoll',
                    'options': options,
                    'multipleAnswers': multipleAnswers,
                    'quotedMsgId': quotedMsgId,
                    'retry': 0
                })
        return msgSid

    def sendFileByUrl(self, to, urlFile, fileName=None, caption=None, quotedMsgId=None):
        chatId = self.getChatId(to)
        fileName = fileName or unquote(self.get_last_url_segment(url=urlFile))
        response = self.greenAPI.sending.sendFileByUrl(chatId=chatId, urlFile=urlFile, fileName=fileName, caption=caption, quotedMessageId=quotedMsgId)
        msgSid = response.data.get('idMessage') if response.data else None
        return msgSid

    def get_last_url_segment(self, url):
        path = urlparse(url).path
        segments = path.strip('/').split('/')
        return segments[-1] if segments else None

    def getLastOutgoingMessages(self, fromMobileNo, quantityOfMessages=1):
        chatId = self.getChatId(fromMobileNo)
        response = self.greenAPI.journals.getChatHistory(chatId=chatId, count=quantityOfMessages)
        return response.data

    def getAuthCode(self, phoneNumber):
        payload = {
            "phoneNumber": phoneNumber
        }

        # Send the POST request to Green API
        response = self.genericApi('getAuthorizationCode', payload)
        pass

    async def handleAction(self, action, payload, max_retries=5, base_delay=1.0):
        async with self.rateLimitManager.semaphore:
            for attempt in range(max_retries):
                allowed = await self.rateLimitManager.wait_until_allowed(action)

                if allowed:
                    try:
                        if eval(f'self.{action}'):
                            response = eval(f'self.{action}')(**payload)
                            self.greenApiLogger.info(f"✅ {action} payload: {payload} response: {response}")
                            if response == None:
                                self.greenApiLogger.warning(f"handleAction: {action} {payload} None response")
                            return response
                        return None
                    except Exception as ex:
                        self.greenApiLogger.error(f"❌ handleAction: Error sending {action} {payload}", ex)
                        await asyncio.sleep(base_delay * 2 ** attempt)

                else:
                    wait_time = base_delay * 2 ** attempt
                    self.greenApiLogger.debug(f"[{action}] Rate limited. Waiting {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
      
    @staticmethod
    def cleanMobileNo(mobileNo):    
        mobileNo = mobileNo.replace(' ','').replace('-','').replace('+','').replace('@c.us','').replace('@g.us','')
        return mobileNo

    def getPollSelection(self, votes):
        for vote in votes or []:
            selected = len(vote['optionVoters']) > 0
            if selected:
                return vote['optionName']
        return None

    async def authenticateGreenApiRequest(self, request: Request):
        """
        Dependency to verify the signature from Twilio.
        """
        # Extract token from headers
        authorizationToken = request.headers.get("Authorization")

        if not authorizationToken:
            raise HTTPException(status_code=403, detail="Authorizatione header is missing.")

        if authorizationToken != f"Bearer {self.greenApiBearerToken}":
            raise HTTPException(status_code=403, detail=f"Invalid Authorization.")
        
        self.logger.info("Received a verified request from GreenApi")

    async def isIncomingMessage(self, request:Request):
        data = await request.json()
        if "messageData" in data and "senderData" in data:
            return True
        return False

    async def handleIncomingWebhook(self, incomingWebhookCallback, request:Request):
        data = await request.json()
        # Extract message ID and status
        message_id = data.get("idMessage")
        status = data.get("status")
        greenApiRequest = None
        repliedAnswer = 'ok'

        # Define statuses to ignore
        failed_statuses = {"not_sent", "failed", "error"}

        if status in failed_statuses:
            self.greenApiLogger.warning(f"❌ Ignoring failed message {message_id} with status: {status}")
            return ({"status": "ignored"}), 200

        # Extract sender chatId and received message
        if "messageData" in data and "senderData" in data:
            to_mobile = self.cleanMobileNo(data["instanceData"]["wid"])
            chatId = data["senderData"]["chatId"]
            fromChatGroupId = ''
            from_mobile = ''
            if chatId.endswith("@g.us"):
                fromChatGroupId = chatId
            else:
                from_mobile = self.cleanMobileNo(chatId)
            senderId = data["senderData"]["sender"]
            from_name = data["senderData"].get("senderName")
            from_mobile = self.cleanMobileNo(senderId)
            message_data = data.get("messageData", {})
            file_message_data = message_data.get("fileMessageData", {})
            type_message = message_data.get("typeMessage", "")

            if from_mobile == self.greenApiSupportWhatsapp or from_mobile == self.adjustMobileNo(self.fromMobile) or fromChatGroupId:                
                if fromChatGroupId in self.chatGroupsToForward:
                    try:
                        headers = {
                            'X-API-Key': '9162de21-4dc0-47b3-bdd6-7e4eb8bef7e7',
                            'Content-Type': 'application/json'
                        }
                        messageBody = message_data.get("textMessageData", {}).get("textMessage", "") or \
                            message_data.get("extendedTextMessageData", {}).get("text", "") or \
                            file_message_data.get("caption", "")
                        msg = {
                            "fromMobile": from_mobile,
                            "fromChatGroupId": fromChatGroupId,
                            "toMobile": to_mobile,
                            "typeMessage": type_message,
                            "messageBody": messageBody,
                            "downloadUrl": file_message_data.get("downloadUrl", ""),
                            "messageSid": message_id,
                        }
                        response = requests.post(
                            self.refalertWebhookUrlTest,
                            json=msg,
                            headers=headers,
                            verify=self.refalertWebhookVerifySsl,
                        )
                        self.logger.info(f"📩 Forward message from group {fromChatGroupId} to refAlert_test: {response.status_code}")
                        if 'testonly' not in messageBody.lower():
                            response = requests.post(
                                self.refalertWebhookUrlProd,
                                json=msg,
                                headers=headers,
                                verify=self.refalertWebhookVerifySsl,
                            )
                            self.logger.info(f"📩 Forward message from group {fromChatGroupId} to refAlert: {response.status_code}")
                        if from_mobile == '972547799979':
                            self.logger.info(f"📩 Forwarded message_data: {message_data}")
                    except Exception as e:
                        self.greenApiLogger.error(f"❌ Error sending message to refAlert: {e}")
                
                else:
                    self.greenApiLogger.info(f"📩 Ignoring message from {from_mobile} {fromChatGroupId}")

                return ({"status": "ignored"}), 200
            
            elif type_message == "textMessage" or type_message == "extendedTextMessage":
                textMessage = message_data.get("textMessageData", {}).get("textMessage", "") or \
                    message_data.get("extendedTextMessageData", {}).get("text", "")
                self.greenApiLogger.info(f"📩 Received message from {from_mobile}: {textMessage}")
                greenApiRequest = {
                    "source": "greenApi",
                    "fromMobile": from_mobile,
                    "fromChatGroupId": fromChatGroupId,
                    "fromName": from_name,
                    "toMobile": to_mobile,
                    "messageBody": textMessage,
                    "buttonId": None,
                    "messageSid": message_id,
                    "latitude": None,
                    "longitude": None,
                    "mediaFiles": None
                }
            elif type_message == "locationMessage":
                latitude = message_data.get("locationMessageData", {}).get("latitude")
                longitude = message_data.get("locationMessageData", {}).get("longitude")
                self.greenApiLogger.info(f"📩 Received location from {from_mobile}: lat:{latitude} lng:{longitude}")
                greenApiRequest = {
                    "source": "greenApi",
                    "fromMobile": from_mobile,
                    "fromChatGroupId": fromChatGroupId,
                    "toMobile": to_mobile,
                    "messageBody": None,
                    "buttonId": None,
                    "messageSid": message_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "mediaFiles": None
                }

            elif type_message == "interactiveButtonsResponse":
                originalMessageSid = message_data.get("interactiveButtonsResponse", {}).get("stanzaId", "")
                originalMessage = self.cacheService.getMessage(originalMessageSid)
                if not originalMessage:
                    self.greenApiLogger.error(f"📩 Received poll update from {from_mobile}, ❌ Message {originalMessageSid} not found")
                else:
                    button_id = message_data.get("interactiveButtonsResponse", {}).get("selectedButtonId", "")
                    if button_id:
                        greenApiRequest = {
                            "source": "greenApi",
                            "fromMobile": from_mobile,
                            "fromChatGroupId": fromChatGroupId,
                            "toMobile": to_mobile,
                            "messageBody": None,
                            "buttonId": button_id,
                            "messageSid": message_id,
                            "latitude": None,
                            "longitude": None,
                            "mediaFiles": None
                        }

            elif type_message == "pollUpdateMessage":
                originalMessageSid = message_data.get("pollMessageData", {}).get("stanzaId", "")
                originalMessage = self.cacheService.getMessage(originalMessageSid)# or {'type':'sendPoll', 'extra':''}
                if not originalMessage:
                    self.greenApiLogger.error(f"📩 Received poll update from {from_mobile}, ❌ Message {originalMessageSid} not found")
                else:
                    votes = message_data.get("pollMessageData", {}).get("votes", "")
                    selectedVote = self.getPollSelection(votes)
                    self.greenApiLogger.info(f"📩 Received poll update from {from_mobile}: {votes} {selectedVote} {originalMessageSid}:{originalMessage.get('extra')}")
                    if selectedVote and originalMessage and originalMessage.get('type', '') == 'sendPoll':
                        if originalMessage.get('extra', ''):
                            extra = originalMessage['extra']
                            if len(extra.split('_')) == 1:
                                extra = f'approveGame_{extra}'
                            action = extra.split('_')[0]
                            input = extra.split('_')[1]
                            button_id = None
                            if action == 'approveGame':
                                gameId = input
                                gameApproved = selectedVote == 'לאשר בפורטל'
                                if gameApproved:
                                    button_id = f'approvegameid_{gameId}'
                                    self.greenApiLogger.info(f"📩 Game {gameId} approved by {from_mobile}")
                            elif action == 'approveJoin':
                                refereeMobile = input
                                joinApproved = selectedVote == 'כן'
                                if joinApproved:
                                    button_id = f'joinconfirmation_yes'
                                    self.greenApiLogger.info(f"📩 Join approved by {refereeMobile}")
                                else:
                                    button_id = f'joinconfirmation_no'
                                    self.greenApiLogger.info(f"📩 Join declined by {refereeMobile}")
                            elif action == 'activate':
                                refId = input
                                activateApproved = selectedVote == 'מאשר'
                                if activateApproved:
                                    button_id = f'activateref_{refId}'
                                    self.greenApiLogger.info(f"📩 Activate approved for {refId}")
                            if button_id:
                                greenApiRequest = {
                                    "source": "greenApi",
                                    "fromMobile": from_mobile,
                                    "fromChatGroupId": fromChatGroupId,
                                    "toMobile": to_mobile,
                                    "messageBody": None,
                                    "buttonId": button_id,
                                    "messageSid": message_id,
                                    "latitude": None,
                                    "longitude": None,
                                    "mediaFiles": None
                                }
                        else:
                            greenApiRequest = {
                                "source": "greenApi",
                                "fromMobile": from_mobile,
                                "fromChatGroupId": fromChatGroupId,
                                "toMobile": to_mobile,
                                "messageBody": selectedVote,
                                "buttonId": None,
                                "messageSid": message_id,
                                "latitude": None,
                                "longitude": None,
                                "mediaFiles": None
                            }
            elif type_message == 'imageMessage' and message_data.get("downloadUrl"):
                media_list = [ message_data["downloadUrl"] ]
                self.greenApiLogger.info(f"📩 Received message with filefrom {from_mobile}: {message_data["downloadUrl"]}")
                greenApiRequest = {
                    "source": "greenApi",
                    "fromMobile": from_mobile,
                    "fromChatGroupId": fromChatGroupId,
                    "fromName": from_name,
                    "toMobile": to_mobile,
                    "messageBody": None,
                    "buttonId": None,
                    "messageSid": message_id,
                    "latitude": None,
                    "longitude": None,
                    "mediaFiles": media_list
                }
            else:
                self.greenApiLogger.warning(f"📩 Received message from {from_mobile}: {message_data}")

            if greenApiRequest:
                reply = await incomingWebhookCallback(greenApiRequest, request)
                repliedAnswer = reply.get('repliedAnswer')
                repliedFileUrl = reply.get('repliedFileUrl')
                repliedFileName = reply.get('repliedFileName')
                repliedAnswerPreview = reply.get('repliedAnswerPreview')
                repliedLocation = reply.get('repliedLocation')

                returnOnly = request.headers.get('ReturnOnly') is not None

                if not returnOnly:
                    if repliedAnswer and repliedFileUrl is None:
                        await self.handleAction('sendMessage', {'to': chatId, 'message': repliedAnswer, 'previewUrl': repliedAnswerPreview})
                    elif repliedFileUrl:
                        await self.handleAction('sendFileByUrl', {'to': chatId, 'urlFile': repliedFileUrl, 'fileName': repliedFileName, 'caption': repliedAnswer or 'מצורף קובץ' })
                    if repliedLocation:
                        await self.handleAction('sendLocation', {'to': chatId, 'latitude': repliedLocation['latitude'], 'longitude': repliedLocation['longitude'], 'name': repliedLocation['name'], 'address': repliedLocation['address'] })

            self.greenApiLogger.info(f"✅ Processed message {message_id} with status: {status}")
            return ({"response": repliedAnswer}), 200
   
        return ({"status": "processed"}), 200

    def download_green_api_media(self, download_url):
        headers = {
            "Authorization": f"Bearer {self.greenApi_auth_token}"
        }
        response = requests.get(download_url, headers=headers)
        if response.ok:
            with open("downloaded_file", "wb") as f:
                f.write(response.content)
            print("File downloaded.")
        else:
            print("Failed to download file:", response.status_code)

    def test(self):
        groupName = 'דוגמא לקבוצת ווטסאפ לצוות שיפוט'
        groupId = None#'120363392424642234@g.us'
        if not groupId:
            groupResponse = self.createGroup(groupName, ['0547799979'])#, '+972 54-640-2507'])
            groupId = groupResponse.data['chatId']
        #response = self.addGroupParticipant(groupId, '0547799979')
        response = self.addGroupParticipant(groupId, '+972 54-640-2507')

    async def stressTest(self, action, payload):
        for i in range(100):
            now = int(time.time())
            response = await self.handleAction(action, payload)
            print(f'{now} {i} {response}')
 
if __name__ == '__main__':
    client = GreenApiClient(logging, None, greenApiInstanceId=os.getenv('greenApiInstanceId'))
    #state = asyncio.run(client.stressTest('getStateInstance', {}))
    buttons = [
        {
            "type": "copy",
            "buttonId": "1",
            "buttonText": "Copy me",
            "copyCode": "3333"
        },
        {
            "type": "call",
            "buttonId": "2",
            "buttonText": "Call me",
            "phoneNumber": "972547799979"
        },
        {
            "type": "url",
            "buttonId": "3",
            "buttonText": "Green-api",
            "url": "https://green-api.com"
        }
    ]
    response = client.sendInteractiveButtons(to='972547799979', header='hello', body='how are you ?', footer='have a good night', buttons=buttons)
    pass
    buttons = [
        {
            "buttonId": "button1111",
            "buttonText": "First Button"
        },
        {
            "buttonId": "button1122",
            "buttonText": "Second Button"
        },
        {
            "buttonId": "button33133",
            "buttonText": "Third Button"
        }
    ]
    response = client.sendInteractiveButtonsReply(to='972547799979', header='hello', body='how are you ?', footer='have a good night', buttons=buttons)
    pass
    exit
    contact = asyncio.run(client.getContacts(group=True, count=10)) 
    pass
    contact = {
        "phoneContact": client.cleanMobileNo(client.fromMobile), 
        "company": "שירות עדכונים והתראות לשופטים"
    }
    #asyncio.run(client.handleAction('sendContact', {'to': '972547799979', 'contact': contact}))

    #msgId = client.createGroup("צהוב נגד אדום", "972547799979")
    #msgId = client.sendMessage("972547799979", f"test {helpers.localNow()}")
    msgId = asyncio.run(client.handleAction(client.getGroupData.__name__, {"chatGroupId":'120363419261445737@g.us'}))
    msgId = asyncio.run(client.handleAction(client.sendMessage.__name__, {"to":"972547799979", "message":f"test {helpers.localNow()}"}))
    newGameMsg = 'שיבוצים:\nתאריך: 15/04/25 16:00\nיום: שלישי\nמסגרת משחקים: ליגת ילדים ב\' דן 1\nמשחק: בית"ר ר"ג דרום "צו פיוס" - מ.ס בני יפו אורתודוכסים\nסבב: 2\nמחזור: 20\nמגרש: רמת גן אימונים\n\nשופט ראשי\n* שם: שחר גיא\n* סטטוס: מאשר\n* דרג: דרג אזורי-טרומים\n* טלפון: 0547799979\n* כתובת: אהרון גולדשטיין 2 גבעתיים\nניתן לאשר אוטומטית בפורטל דרך הקישור הבא https://api.refereex.com:24501/api/approveGame/43679/2d5d8c91/492b9aa4\nעדכון לוח שנה https://api.refereex.com:24501/api/file/492b9aa4'
    #newGameMsg = 'הודעה מקורית'
    #msgId = client.sendMessage("972547799979", newGameMsg)
    response = client.sendPoll("972547799979", newGameMsg, None)
    #response = client.getLastOutgoingMessages("972547799979", 10)
    exit
    mobileNos = [
        "0548042664",
        "0526727844",
        "0523414717"
    ]
    for no in mobileNos:
        response = client.checkWhatsapp(no)

    pass