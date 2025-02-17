from heyoo import WhatsApp
from datetime import datetime
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import logging
import json

class WhatsappApi:
    def __init__(self, fromMobile=None):

        try:
            account_sid = helpers.get_secret('twilio_account_sid')#refPortalSecret and refPortalSecret.get("twilio_account_sid", None)
            auth_token = helpers.get_secret('twilio_auth_token')#refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
            access_token = helpers.get_secret('whastapp_access_token')#refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
            logging.getLogger("twilio").setLevel(logging.WARNING)
            self.logger = logging.getLogger(__name__)
            self.whatsappClient = WhatsApp(access_token,phone_number_id=fromMobile)
            self.fromMobile = fromMobile

        finally:
            pass

    async def getOriginalTemplate(self, refereeDetail, originalRepliedMessageSid, currentMessageSid, messageBody):
        if not refereeDetail:
            return
        
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/refId{refereeDetail["refId"]}.json'
        templatesMessages = helpers.load_from_file(referee_file_path)
        self.logger.info(f'refId={refereeDetail["refId"]}, templates={len(templatesMessages)}')
        templateMessage = templatesMessages.get(originalRepliedMessageSid)
        if templateMessage:
            templateMessage['replyMessageSid'] = currentMessageSid
            templateMessage['repliedAnswer'] = messageBody
            templateMessage['replyDate'] = helpers.datetime_to_str(datetime.now())
        helpers.save_to_file(templatesMessages, referee_file_path)

        return templateMessage
    
    async def sendUsingContentTemplate(self, refId, toMobile, contentSid, contentVariables, additionalInfo, sendAt = None):
        if not contentSid:
            return
        
        try:
            sentWhatsappMessage = None
            contentVariablesJson=helpers.save_to_json(contentVariables)

            if self.twilioServiceId:
                sentWhatsappMessage = self.whatsappClient.messages.create(
                    validity_period = 3600,
                    content_sid=contentSid,
                    to = f'whatsapp:{toMobile}',
                    content_variables=contentVariablesJson,
                    messaging_service_sid=self.twilioServiceId,              
                    send_at = sendAt
                )
            elif self.twilioFromMobile:
                sentWhatsappMessage = self.whatsappClient.messages.create(
                    validity_period = 3600,
                    content_sid=contentSid,
                    from_ = f'whatsapp:{self.twilioFromMobile}',
                    to = f'whatsapp:{toMobile}',
                    content_variables=contentVariablesJson,
                    send_at = sendAt
                )

            obj = {}
            obj[sentWhatsappMessage.sid] = {'refId': refId, 'created': datetime.now().strftime("%Y%m%d%H%M%S"), 'mobile': toMobile, 'contentSid': contentSid, 'msgId': sentWhatsappMessage.sid, 'status': sentWhatsappMessage.status, 'additionalInfo': additionalInfo, 'replyMessageSid': '', 'repliedAnswer': '', 'replyDate': None, 'action': ''}
            referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/refId{refId}.json'
            helpers.append_to_file(obj, referee_file_path)

            self.logger.debug(f'Whatsapp message.id: {sentWhatsappMessage.sid} {sentWhatsappMessage.status}')

            return sentWhatsappMessage
        except Exception as e:
            pass
        
    async def sendFreeText(self, toMobile, message, sendAt = None):
        sizeLimit = 1500
        chunks = helpers.split_text(message, sizeLimit)
        i=0
        sentWhatsappMessage = None
        for chunk in chunks:
            if len(chunks) == 1:                
                message2 = chunk
            else:
                i+=1
                message2 = f'#{i} {chunk}'
     
            if self.twilioServiceId:
                sentWhatsappMessage = self.whatsappClient.messages.create(
                    validity_period = 3600,
                    messaging_service_sid=self.twilioServiceId,              
                    to = f'whatsapp:{toMobile}',
                    body = f'{message2}',
                    send_at = sendAt
                )
            elif self.twilioFromMobile:
                sentWhatsappMessage = self.whatsappClient.messages.create(
                    validity_period = 3600,
                    from_ = f'whatsapp:{self.twilioFromMobile}',
                    to = f'whatsapp:{toMobile}',
                    body = f'{message2}',
                    send_at = sendAt
                )

        self.logger.debug(f'Whatsapp message.id: {sentWhatsappMessage.sid} {sentWhatsappMessage.status}')

        return sentWhatsappMessage

    def lookups(self, mobile):
        try:
            lookups = self.whatsappClient.lookups \
                .v1 \
                .phone_numbers(mobile) \
                .fetch(type="carrier")
            
            return lookups
        except Exception as e:
            self.logger.error(e)
            return None

    def testSend(self, toMobile, param1, param2, param3):
        to_whatsapp_number = f'{toMobile}'     # Recipient's WhatsApp number
        content_sid="",
        messaging_service_sid = 'MG7ec40f0e4baff9a172ad9e78cbc3d269'

        # Template parameters
        template_parameters = {
            "1": param1,                          # Customer name
            "2": param2,  # Content link
            "3": param3                  # Business name
        }

        message = None
        if False:
            message = self.whatsappClient.messages.create(
                validity_period = 3600,
                messaging_service_sid=messaging_service_sid,
                #from_ = f'whatsapp:{self.twilioFromMobile }',
                to = f'whatsapp:{toMobile}',
                body = f'{param1}{param2}',
            )
        
        else:
            message = self.whatsappClient.messages.create(
                content_sid="HXcd4d9925989864a67f1c5c566e5c797b",
                #from_ = f'whatsapp:{self.twilioFromMobile }',
                to = f'whatsapp:{toMobile}',
                content_variables=json.dumps({"name": 'גיא'}),
                messaging_service_sid=messaging_service_sid,
            )

        print(f"Message sent! SID: {message.sid}")

if __name__ == '__main__':
    client = TwilioClient(os.environ.get('twilioServiceId'))
    client.testSend('+972547799979', 'a', 'b', 'c')
    #result = client.lookups('+972547799979')
    pass