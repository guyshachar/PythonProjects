from twilio.rest import Client as TwilioRestClient
from datetime import datetime,timezone
import threading
import asyncio
import uuid
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import logging
import json

class TwilioClient:
    def __init__(self, fromMobile=None, twilioServiceId=None):
        try:
            account_sid = helpers.get_secret('twilio_account_sid')#refPortalSecret and refPortalSecret.get("twilio_account_sid", None)
            auth_token = helpers.get_secret('twilio_auth_token')#refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
            logging.getLogger("twilio").setLevel(logging.WARNING)
            self.logger = logging.getLogger(__name__)
            self.twilioClient = TwilioRestClient(account_sid, auth_token)
            self.twilioFromMobile = fromMobile
            self.twilioServiceId = twilioServiceId

            self.twilioSend = eval(os.environ.get('twilioSend') or 'False')
            self.twilioAddMedia = eval(os.environ.get('twilioAddMedia') or 'False')
            self.apiServiceUrlBase = os.environ.get('apiServiceUrlBase')

        finally:
            pass

    async def getOriginalTemplateBySid(self, refereeDetail, originalRepliedMessageSid, currentMessageSid, buttonId, messageBody):
        if not refereeDetail:
            return
        
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/refId{refereeDetail["refId"]}.json'
        templatesMessages = helpers.load_from_file(referee_file_path)
        self.logger.info(f'refId={refereeDetail["refId"]}, templates={len(templatesMessages)}')
        templateMessage = templatesMessages.get(originalRepliedMessageSid)
        if templateMessage:
            templateMessage['replyMessageSid'] = currentMessageSid
            templateMessage['repliedButtonId'] = buttonId
            templateMessage['repliedAnswer'] = messageBody
            templateMessage['replyDate'] = helpers.datetime_to_str(datetime.now())
            helpers.save_to_file(templatesMessages, referee_file_path)

        return templateMessage
   
    def loadMessages(self, filePath=None, file=None):
        #self.logger.info('load messages...')
        try:
            file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}messages/messages.json'
            self.messages = helpers.load_from_file(file_path)
        except Exception as ex:
            self.logger.error(f'loadMessages {ex}')

    def writeMessages(self):
        try:
            messagesFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}messages/messages.json'
            helpers.save_to_file(self.messages, messagesFilePath)
        except Exception as ex:
            self.logger.error(f'writeMessages {ex}')

    async def sendUsingContentTemplate(self, toMobile, contentSid, contentVariables = None, mediaUrl = None, sendAt = None):
        if not contentSid:
            return
        
        try:
            sentWhatsappMessage = None
            msgSid = None
            status = None
            contentVariablesFixed = {}
            if contentVariables:
                for key in contentVariables:
                    contentVariablesFixed[key] = contentVariables[key].replace('\n', '\r')
            contentVariablesJson = helpers.save_to_json(contentVariablesFixed)

            media = None
            if self.twilioAddMedia and mediaUrl:
                media = [ mediaUrl ]

            if self.twilioServiceId:
                if self.twilioSend:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        content_sid=contentSid,
                        to = f'whatsapp:{toMobile}',
                        content_variables = contentVariablesJson,
                        messaging_service_sid = self.twilioServiceId,
                        media_url = media,              
                        send_at = sendAt,
                        status_callback = f'{self.apiServiceUrlBase}statusCallback'
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]
                self.messages[msgSid] = {
                        'originalMessageSid': msgSid,
                        'contentSid': contentSid,
                        'messagingServiceSid': self.twilioServiceId,
                        'to': f'whatsapp:{toMobile}',
                        'contentVariablesJson': contentVariablesJson,
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage,
                        'retry': 0
                    }       
      
                self.logger.debug(f'{type(sentWhatsappMessage)} {msgSid} {contentSid} {toMobile} {self.twilioServiceId} {contentVariablesJson}')
            elif self.twilioFromMobile:
                if self.twilioSend:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        content_sid = contentSid,
                        from_ = f'whatsapp:{self.twilioFromMobile}',
                        to = f'whatsapp:{toMobile}',
                        content_variables = contentVariablesJson,
                        media_url = media,
                        send_at = sendAt,
                        status_callback = f'{self.apiServiceUrlBase}statusCallback'
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]
                self.messages[msgSid] = {
                        'contentSid': contentSid,
                        'from': f'whatsapp:{self.twilioFromMobile}',
                        'to': f'whatsapp:{toMobile}',
                        'contentVariablesJson': contentVariablesJson,
                        'mediaUrl': mediaUrl,
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage,
                        'retry': 0
                    }       

            self.logger.debug(f'Whatsapp message.id: {msgSid}')

            self.writeMessages()
            return msgSid
        except Exception as ex:
            pass

    async def sendFreeText(self, toMobile, message, mediaUrl = None, sendAt = None):
        sizeLimit = 1500
        chunks = helpers.split_text(message, sizeLimit)
        i=0
        sentWhatsappMessage = None
        msgSid = None
        status = None

        media = None

        for chunk in chunks:
            if len(chunks) == 1:                
                message2 = chunk
                if self.twilioAddMedia and mediaUrl:
                    media = [ mediaUrl ]
            else:
                i+=1
                message2 = f'#{i} {chunk}'
     
            if self.twilioServiceId:
                if self.twilioSend:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        messaging_service_sid=self.twilioServiceId,              
                        to = f'whatsapp:{toMobile}',
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
                        'to': f'whatsapp:{toMobile}',
                        'body': f'{message2}',
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage
                    }       

            elif self.twilioFromMobile:
                if self.twilioSend:
                    sentWhatsappMessage = self.twilioClient.messages.create(
                        validity_period = 3600,
                        from_ = f'whatsapp:{self.twilioFromMobile}',
                        to = f'whatsapp:{toMobile}',
                        body = f'{message2}',
                        media_url = media,
                        send_at = sendAt
                    )
                    msgSid = sentWhatsappMessage.sid
                    status = sentWhatsappMessage.status
                else:
                    msgSid = str(uuid.uuid4())[:8]

                messagesObj = {
                        'from': f'whatsapp:{self.twilioFromMobile}',
                        'to': f'whatsapp:{toMobile}',
                        'body': f'{message2}',
                        'sendAt': sendAt,
                        'status': status,
                        'sentWhatsappMessage': sentWhatsappMessage
                    }       
            
            #self.writeMessages()
        
        self.logger.debug(f'Whatsapp message.id: {msgSid} {sentWhatsappMessage}')

        return msgSid

    def lookups(self, mobile):
        try:
            lookups = self.twilioClient.lookups \
                .v1 \
                .phone_numbers(mobile) \
                .fetch(type="carrier")
            
            return lookups
        except Exception as e:
            self.logger.error(e)
            return None

    def getMessageStatus(self, messageSid):
        try:
            messageStatus = self.twilioClient.messages.get(messageSid)
            return messageStatus
        except Exception as e:
            self.logger.error(e)
            return None

    def getMessagesListByMobile(self, fromMobile, toMobile):
        try:
            messagesList = self.twilioClient.messages.list(from_=f'{fromMobile}', to=f'{toMobile}', limit = 5, page_size= 5)
            return messagesList
        except Exception as e:
            self.logger.error(e)
            return None

    def checkIfWindowIsOpen(self, fromMobile):
        # Fetch last message from user
        messages = self.twilioClient.messages.list(from_=f'whatsapp:{fromMobile}', limit=1)

        if messages and len(messages) > 0:
            last_message_time = messages[0].date_sent.replace(tzinfo=timezone.utc)
            time_difference = datetime.now(timezone.utc) - last_message_time

            if time_difference.total_seconds() < 24*60*60:
                return (True, last_message_time)
            else:
                return (False, last_message_time)
        else:
            return (False, None)

    async def testSend(self, toMobile, param1, param2, param3):
        to_whatsapp_number = f'whatsapp:{toMobile}'
        messaging_service_sid = 'MG7ec40f0e4baff9a172ad9e78cbc3d269'
       
        self.loadMessages()
        
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
            content_sid = os.environ.get('twilioNewGameContentSid')
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
                from_ = f'whatsapp:{self.twilioFromMobile }',
                to = f'whatsapp:{toMobile}',
                body = f'{param1}{param2}',
            )
        
        else:
            msgSid = await self.sendUsingContentTemplate(
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

if __name__ == '__main__':
    file = ''
    leagueId = file[file.find('leagueId')+8:].rstrip('.json')

    client = TwilioClient(fromMobile=os.environ.get('twilioFromMobile'),twilioServiceId=os.environ.get('twilioServiceId'))
    #logging.basicConfig(level=logging.DEBUG)
    #isOpen = client.checkIfWindowIsOpen('+972525253248')
    asyncio.run(client.testSend('+972547799979', 'a', 'b', 'c'))
    #result = client.lookups('+972547799979')
    pass