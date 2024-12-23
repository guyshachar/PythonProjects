from twilio.rest import Client as TwilioRestClient
import helpers
import logging

class TwilioClient:
    def __init__(self, parent, fromMobile):
        if parent:
            self.logger = parent.logger
        else:
            self.logger = logging.getLogger(__name__)

        try:
            account_sid = helpers.get_secret('twilio_account_sid')#refPortalSecret and refPortalSecret.get("twilio_account_sid", None)
            auth_token = helpers.get_secret('twilio_auth_token')#refPortalSecret and refPortalSecret.get("twilio_auth_token", None)
            logging.getLogger("twilio").setLevel(logging.WARNING)
            self.twilioClient = TwilioRestClient(account_sid, auth_token)
            self.twilioFromMobile = fromMobile
        finally:
            pass

    async def send(self, toMobile, message, sendAt = None):
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
     
            sentWhatsappMessage = self.twilioClient.messages.create(
                validity_period = 3600,
                from_ = f'whatsapp:{self.twilioFromMobile }',
                to = f'whatsapp:{toMobile}',
                body = f'{message2}',
                send_at = sendAt
            )

        self.logger.debug(f'Whatsapp message.id: {sentWhatsappMessage.sid} {sentWhatsappMessage.status}')

        return sentWhatsappMessage
