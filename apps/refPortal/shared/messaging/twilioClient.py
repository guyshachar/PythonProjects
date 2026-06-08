from twilio.rest import Client as TwilioRestClient
from twilio.twiml.messaging_response import MessagingResponse
from twilio.request_validator import RequestValidator
from datetime import datetime, timezone, timedelta
import logging
import asyncio
import uuid
import os
import json
import sys
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from zoneinfo import ZoneInfo
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.messaging.messagingClientBase import MessagingClientBase
from shared.db import CacheService

class TwilioClient(MessagingClientBase):
    def __init__(self, logger:Logger, cacheService:CacheService, fromMobile=None, twilioServiceId=None, useClient:bool=False):
        try:
            super().__init__(logger=logger, cacheService=cacheService, clientName='twilio', fromMobile=fromMobile, useClient=useClient)
            self.logger = logger
            self.cacheService = cacheService

            self.twiliioLogger = logger
            logging.getLogger("twilio").setLevel(logging.WARNING)
            #logging.getLogger("twilio").setLevel(logging.ERROR)

            account_sid = helpers.get_secret('twilio_account_sid')#refPortalSecret and refPortalSecret.get("twilio_account_sid", None)
            auth_token = helpers.get_secret('twilio_auth_token')#refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
            self.twilioClient = TwilioRestClient(account_sid, auth_token)
            self.twilioServiceId = twilioServiceId
            self.incomingApiGuid = helpers.get_secret('incoming_api_guid')

            self.twilioAddMedia = eval(os.getenv('twilioAddMedia') or 'False')
            self.twilioServiceUrlBase = f"{os.getenv('twilioServiceUrlBase')}{self.incomingApiGuid}/"
            self.twilioEnableStatucCallback = eval(os.getenv('twilioEnableStatucCallback') or 'False')
            self.validator = RequestValidator(auth_token)

            self.docsServiceUrlBase = os.getenv('docsServiceUrlBase')

            self.twiliioLogger.info(f'twilioClient starts...')

        finally:
            pass

    def getOriginalTemplateBySid(self, refereeDetail, originalMessageSid, currentMessageSid, buttonId, messageBody):
        if not refereeDetail:
            return
        
        referee_file_path = f'{os.getenv("MY_DATA_FOLDER", f"/run/data/")}referees/templates/refId{refereeDetail["refId"]}.json'
        templatesMessages = jsonHelper.load_from_file(referee_file_path)
        self.twiliioLogger.info(f'refId={refereeDetail["refId"]}, templates={len(templatesMessages)}')
        templateMessage = templatesMessages.get(originalMessageSid)
        if templateMessage:
            templateMessage['replyMessageSid'] = currentMessageSid
            templateMessage['repliedButtonId'] = buttonId
            templateMessage['repliedAnswer'] = messageBody
            templateMessage['replyDate'] = jsonHelper.datetime_to_str(helpers.localNow())
            jsonHelper.save_to_file(templatesMessages, referee_file_path)

        return templateMessage
   
    def sendUsingContentTemplate(self, toMobile, contentSid, contentVariables = None, mediaUrl = None, sendAt = None):
        if not contentSid:
            return
        
        try:
            sentWhatsappMessage = None
            msgSid = None
            status = None
            contentVariablesFixed = {}
            if contentVariables:
                for key in contentVariables:
                    if contentVariables[key]:
                        contentVariablesFixed[key] = str(contentVariables[key]).replace('\n', '\r')
            contentVariablesJson = jsonHelper.save_to_json(contentVariablesFixed, True)

            media = None
            if self.twilioAddMedia and mediaUrl:
                media = [ mediaUrl ]

            if self.twilioServiceId:
                if self.useClient:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        content_sid=contentSid,
                        to = f'whatsapp:{toMobile}',
                        content_variables = contentVariablesJson,
                        messaging_service_sid = self.twilioServiceId,
                        media_url = media,              
                        send_at = sendAt,
                        status_callback = f'{self.twilioServiceUrlBase}statusCallback' if self.twilioEnableStatucCallback else None
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]

                self.cacheService.setMessage(msgSid, 
                    {
                        'originalMessageSid': msgSid,
                        'contentSid': contentSid,
                        'messagingServiceSid': self.twilioServiceId,
                        'to': f'whatsapp:{toMobile}',
                        'contentVariables': contentVariablesFixed,
                        'sendAt': sendAt,
                        'status': status,
                        #'sentWhatsappMessage': sendWhatsappMessageJson,
                        'retry': 0
                    })
                self.twiliioLogger.debug(f'{type(sentWhatsappMessage)} {msgSid} {contentSid} {toMobile} {self.twilioServiceId} {contentVariablesJson}')
            elif self.fromMobile:
                if self.useClient:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        content_sid = contentSid,
                        from_ = f'whatsapp:{self.fromMobile}',
                        to = f'whatsapp:{toMobile}',
                        content_variables = contentVariablesJson,
                        media_url = media,
                        send_at = sendAt,
                        status_callback = f'{self.twilioServiceUrlBase}statusCallback' if self.twilioEnableStatucCallback else None
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]

                self.cacheService.setMessage(msgSid, 
                    {
                        'contentSid': contentSid,
                        'from': f'whatsapp:{self.fromMobile}',
                        'to': f'whatsapp:{toMobile}',
                        'contentVariablesJson': contentVariablesJson,
                        'mediaUrl': mediaUrl,
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage,
                        'retry': 0
                    })

            self.twiliioLogger.debug(f'Whatsapp message.id: {msgSid}')

            return msgSid
        except Exception as ex:
            self.twiliioLogger.error(f'sendUsingContentTemplate {toMobile}', ex)

    async def sendMessage(self, to, message, mediaUrl = None, sendAt = None, previewUrl = False):
        sizeLimit = 1599
        chunks = helpers.split_text(message, sizeLimit)
        i=0
        sentWhatsappMessage = None
        msgSid = None
        status = None

        media = None

        for chunk in chunks:
            if len(chunks) == 1:                
                message2 = chunk
                if previewUrl == False:
                    message2 = message2.replace("://", ":​//")
                if self.twilioAddMedia and mediaUrl:
                    media = [ mediaUrl ]
            else:
                i+=1
                message2 = f'#{i} {chunk}'
     
            if self.twilioServiceId:
                if self.useClient:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        messaging_service_sid=self.twilioServiceId,              
                        to = f'whatsapp:{to}',
                        body = f'{message2}',
                        media_url = media,
                        send_at = sendAt
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]

                messagesObj = {
                        'messagingServiceSid': self.twilioServiceId,
                        'to': f'whatsapp:{to}',
                        'body': f'{message2}',
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage
                    }       

            elif self.fromMobile:
                if self.useClient:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        from_ = f'whatsapp:{self.fromMobile}',
                        to = f'whatsapp:{to}',
                        body = f'{message2}',
                        media_url = media,
                        send_at = sendAt
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]

                messagesObj = {
                        'from': f'whatsapp:{self.fromMobile}',
                        'to': f'whatsapp:{to}',
                        'body': f'{message2}',
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage
                    }       
            
            #self.writeMessages()
        
        self.twiliioLogger.debug(f'Whatsapp message.id: {msgSid} {sentWhatsappMessage}')

        return msgSid

    def lookups(self, mobileNo):
        try:
            lookups = self.twilioClient.lookups \
                .v1 \
                .phone_numbers(mobileNo) \
                .fetch(type="carrier")
            
            return lookups
        except Exception as ex:
            self.twiliioLogger.error(ex)
            return None

    def getMessageStatus(self, messageSid):
        try:
            messageStatus = self.twilioClient.messages.get(messageSid)
            return messageStatus
        except Exception as ex:
            self.twiliioLogger.error(ex)
            return None

    def getMessagesListByMobile(self, fromMobile, toMobile):
        try:
            messagesList = self.twilioClient.messages.list(from_=f'{fromMobile}', to=f'{toMobile}', limit = 5, page_size= 5)
            return messagesList
        except Exception as ex:
            self.twiliioLogger.error(ex)
            return None

    def checkIfWindowIsOpen(self, fromMobile):
        # Fetch last message from user
        messages = self.twilioClient.messages.list(from_=f'whatsapp:{fromMobile}', limit=1)

        if messages and len(messages) > 0 and messages[0].date_sent:
            #print(messages[0])
            #self.logger.info(f'{fromMobile} {len(messages)} {messages[0].body}')
            lastMessageTime = messages[0].date_sent.replace(tzinfo=timezone.utc)
            timeElapsed = datetime.now(timezone.utc) - lastMessageTime

            if timeElapsed.total_seconds() < 24*60*60:
                return (True, lastMessageTime, timeElapsed)
            else:
                return (False, lastMessageTime, timeElapsed)
        else:
            return (False, None, None)

    def testSend(self, toMobile, param1, param2, param3):
        to_whatsapp_number = f'whatsapp:{toMobile}'
        messaging_service_sid = 'MG7ec40f0e4baff9a172ad9e78cbc3d269'
               
        content_sid = None
        variables = None

        if False: 
            content_sid = 'HXcccda4886ed0b18e2bc573b3e25457d3'
            variables = {
                    'messageTitle': 'נתניה-יהודה',
                    'notice11Title': 'התראה ראשונה',
                    'game22Title': 'ליגת ותיקים',
                    'notice33Details': 'המשחק מתחיל בעוד 24 שעות'
                }            
        elif False:
            content_sid = os.getenv('twilioNewGameContentSid')
            variables = {
                        'date': 'רביעי 20/01/2025',
                        #'dow': 'רביעי',
                        'tournament': 'ליגת ותיקים',
                        'game': 'נתניה-אשדוד',
                        'round': '2',
                        'week': '12',
                        'field': 'ספורטק',
                        'status': 'מאשר',
                        'referees': 'שופט ראשי'
                    }
        else:
            content_sid = 'HXb263638fa216c9c64c8cb7c65ee8f2f2'
            variables = {}

        message = None
        if False:
            message = self.twilioClient.messages.create(
                validity_period = 3600,
                #messaging_service_sid=messaging_service_sid,
                from_ = f'whatsapp:{self.fromMobile }',
                to = f'whatsapp:{toMobile}',
                body = f'{param1}{param2}',
            )
        
        else:
            msgSid = self.sendUsingContentTemplate(
                toMobile=toMobile,
                contentSid=content_sid,
                contentVariables=variables,
                sendAt=None
            )

        print(f"Message sent! SID: {msgSid}")
        return
        sid = message.sid
        while True:
        #sid = 'MMe125190c627128eb069380dcedbdcced'
            status = self.getMessageStatus(sid)
            messagesList = self.getMessagesListByMobile(toMobile)
            pass
        pass

    def findFailedMessages(self):
        sentAfterUTC = helpers.localNow().astimezone(ZoneInfo("UTC")) - timedelta(minutes=60)
        messages = self.twilioClient.messages.list(to=f'whatsapp:{self.fromMobile}', date_sent_after=sentAfterUTC)

        # Filter messages with error code 502
        failedMessages = [msg for msg in messages if msg.error_code == 11200]

        # Resend each failed message    
        for msg in failedMessages:
            print(f"Resending to {msg.to}: {msg.body}")

            new_message = client.messages.create(
                to=msg.to,
                from_=msg.from_,
                body=msg.body
            )

            print(f"New Message SID: {new_message.sid}")

    async def authenticateTwilioRequest(self, request: Request):
        """
        Dependency to verify the signature from Twilio.
        """
        # Twilio sends data as form-encoded, not JSON
        form_data = await request.form()

        #expected_signature = self.validator.compute_signature(str(request.url.path), form_data)
        x_twilio_signature = request.headers.get('X-Twilio-Signature')
        self.logger.debug(f'x_twilio_signature={x_twilio_signature}')
        if not x_twilio_signature:
            #self.logger.error(f'X-Twilio-Signature header is missing.')
            raise HTTPException(status_code=403, detail="X-Twilio-Signature header is missing.")
        
        # The validator needs the full URL
        url = str(request.url)
        
        if not self.validator.validate(url, form_data, x_twilio_signature):
            self.logger.error(f'Invalid Twilio signature.')
            self.logger.debug(url)
            self.logger.debug(dict(request.headers))
            self.logger.debug(await request.form())
            raise HTTPException(status_code=403, detail=f"Invalid Twilio signature. {x_twilio_signature}")
        
        self.logger.info("Received a verified request from Twilio")

    async def isIncomingMessage(self, request:Request):
        return True

    async def handleIncomingWebhook(self, incomingWebhookCallback, alwaysSendMessage, request:Request):
        data = await request.form()
        now = helpers.localNow()
        current_message_sid = data.get('MessageSid')
        original_message_sid = data.get('OriginalRepliedMessageSid')
        from_mobile = data.get('From')
        fromMobileNo = from_mobile.lstrip('whatsapp:')
        to_number = data.get('To')
        message_body = data.get('Body')
        button_id = data.get('ButtonPayload')
        latitude = data.get('Latitude')
        longitude = data.get('Longitude')
        num_media = int(data.get('NumMedia', '0'))
        media_files = []
        for i in range(num_media):
            media_url = data.get(f"MediaUrl{i}")
            content_type = data.get(f"MediaContentType{i}")
            media_files.append({"url": media_url, "type": content_type})

        twilioRequest = {
            "source": "twilio",
            "fromMobile": fromMobileNo,
            "toMobile": to_number,
            "messageBody": message_body,
            "buttonId": button_id,
            "messageSid": current_message_sid,
            "originalMessageSid": original_message_sid,  # Original message ID for interactive button replies
            "latitude": latitude,
            "longitude": longitude,
            "mediaFiles": media_files
        }

        reply = await incomingWebhookCallback(twilioRequest, request)
        repliedAnswer = reply.get('repliedAnswer')
        repliedFileUrl = reply.get('repliedFileUrl')
        repliedFileName = reply.get('repliedFileName')

        response = MessagingResponse()
        msg = None
        returnOnly = request.headers.get('ReturnOnly') is not None
        
        if repliedAnswer:
            elapsed = helpers.localNow() - now
            if repliedFileUrl and repliedFileName:
                repliedAnswer += f'\nמצורף קובץ {repliedFileName}'
            if alwaysSendMessage or elapsed.total_seconds() > 15:
                if not returnOnly:
                    await self.sendMessage(to=fromMobileNo, message=repliedAnswer)
            msg = response.message(body=repliedAnswer[:1600])

        if repliedFileUrl:
            msg.media(repliedFileUrl)

        return str(response), 200  # Respond with Twilio XML response

def readWA():
    filename = f'{os.getenv("MY_DATA_FOLDER", f"/run/data/")}whatsappmessage'
    with open(filename, 'r') as file:
        while True:
            ch = file.read(1)  # Read one character
            if not ch:
                break  # Stop at EOF            
            print(f'ch={ch} asc={ascii(ch)} ord={ord(ch)}')

if __name__ == '__main__':
    #readWA()
    #pass
    client = TwilioClient(logger=logging, dbClient=None, fromMobile=os.getenv('twilioFromMobile'),twilioServiceId=os.getenv('twilioServiceId'), useClient=True)
    lookupsMobile = client.lookups('+972504216990')

    #logging.basicConfig(level=logging.DEBUG)
    #isOpen = client.checkIfWindowIsOpen('+972525253248')
    #asyncio.run(client.testSend('+972547799979', 'a', 'b', 'c'))
    #asyncio.run(client.findFailedMessages())
    message = 'https://www.refereex.com/images/RefereeX.png'
    asyncio.run(client.sendMessage('+972547799979', message))
    #result = client.lookups('+972547799979')
    pass

'''
Webhook Request from Twilio example
SmsMessageSid=SM30e05d3e95ca9070f4d67586476d8a97&NumMedia=0&ProfileName=%D7%92%D7%99%D7%90+%D7%A9%D7%97%D7%A8&MessageType=text&SmsSid=SM30e05d3e95ca9070f4d67586476d8a97&WaId=972547799979&SmsStatus=received&Body=sfdsfsdfsdfsdf&To=whatsapp%3A%2B972533932474&MessagingServiceSid=MG7ec40f0e4baff9a172ad9e78cbc3d269&NumSegments=1&ReferralNumMedia=0&MessageSid=SM30e05d3e95ca9070f4d67586476d8a97&AccountSid=ACc28a1c0a3ee4b2d606c0250819f8ae85&From=whatsapp%3A%2B972547799979&ApiVersion=2010-04-01

'''