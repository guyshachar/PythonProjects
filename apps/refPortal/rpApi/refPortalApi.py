from flask import Flask, render_template, request, redirect, url_for, jsonify
import asyncio
import json
import sys
import logging
import socket
import os
from twilio.twiml.messaging_response import MessagingResponse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
# Add the rpService directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.handleUsers import HandleUsers
import shared.handleTournaments as handleTournaments #import refreshLeaguesTables, approveGame
from shared.twilioClient import TwilioClient
import shared.helpers as helpers

class RefPortalApi():
    def __init__(self):
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        self.handleUsers = HandleUsers()

        (self.refereesDetails, self.refereesByMobile) = self.handleUsers.getAllReferesByMobile()
        
        self.twilioClient = TwilioClient(twilioServiceId='+14155238886')

        openText=f'Ref Portal Api {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        self.logger.info(openText)
        
        self.app = Flask(__name__)

        self.app.add_url_rule('/', 'root', self.root, methods=['GET'])
        self.app.add_url_rule('/welcome', 'welcome', self.welcome, methods=['GET'])
        self.app.add_url_rule('/health', 'health', self.health, methods=['GET'])
        self.app.add_url_rule('/getReferee', 'getReferee', self.getReferee, methods=['GET'])
        self.app.add_url_rule('/getReferee', 'getRefereeSubmit', self.getRefereeSubmit, methods=['POST'])
        self.app.add_url_rule('/addPending', 'addPending', self.addPending, methods=['GET'])
        self.app.add_url_rule('/addPending', 'addPendingSubmit', self.addPendingSubmit, methods=['POST'])
        self.app.add_url_rule('/registration', 'registration', self.registration, methods=['GET'])
        self.app.add_url_rule('/registration', 'registrationSubmit', self.registrationSubmit, methods=['POST'])
        self.app.add_url_rule('/changePassword', 'changePassword', self.changePassword, methods=['GET'])
        self.app.add_url_rule('/changePassword', 'changePasswordSubmit', self.changePasswordSubmit, methods=['POST'])
        self.app.add_url_rule('/activate', 'activate', self.activate, methods=['GET'])
        self.app.add_url_rule('/activate', 'activateSubmit', self.activateSubmit, methods=['POST'])
        self.app.add_url_rule('/changePassword', 'changePassword', self.changePassword, methods=['GET'])
        self.app.add_url_rule('/changePassword', 'changePasswordSubmit', self.changePasswordSubmit, methods=['POST'])
        self.app.add_url_rule('/deactivate', 'deactivate', self.deactivate, methods=['GET'])
        self.app.add_url_rule('/deactivate', 'deactivateSubmit', self.deactivateSubmit, methods=['POST'])
        self.app.add_url_rule('/refreshLeaguesTables', 'refreshLeaguesTables', self.refreshLeaguesTables, methods=['GET'])
        self.app.add_url_rule('/refreshLeaguesTables', 'refreshLeaguesTablesSubmit', self.refreshLeaguesTablesSubmit, methods=['POST'])
        #self.app.add_url_rule('/api/approveGame/<refId>/<gameId>', 'approveGameSubmit', self.approveGameSubmit, methods=['GET'])
        self.app.add_url_rule('/reloadReferees', 'reloadReferees', self.reloadReferees, methods=['GET'])
        self.app.add_url_rule('/incomingWebhook', 'incomingWebhook', self.incomingWebhook, methods=['POST'])

    async def start(self):
        try:
            self.logger.info('start')
            ssl_file_path = f'{os.getenv("MY_SSL_FILE", "/run/ssl/")}'
            self.app.run(host='0.0.0.0', debug=True, port=5001, ssl_context=(f'{ssl_file_path}cert.pem', f'{ssl_file_path}key.pem'))     
        except Exception as e:
            self.logger.error(json.dumps(e))

    async def root(self):
        return redirect(url_for('welcome'))  # Redirects to the 'home' route

    async def welcome(self):
        return render_template('welcome.html')
    
    async def health(self):
        logging.info('health')
        return f'Health is ok {datetime.now()}...'

    async def getReferee(self):
        return render_template('getReferee.html')

    async def getRefereeSubmit(self):       
        refId = request.form.get('refId').strip()
        
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = RefPortalApi.handleUsers.getRefereeDetail(refId)
        if 'password' in result:
            del result['password']

        if result:
            return f"{result}\n{datetime.now()}"
        else:
            return f"{datetime.now()} קוד שופט {refId} לא נמצא, אנא פנה למנהל המערכת"

    async def addPending(self):
        return render_template('addPending.html')

    async def addPendingSubmit(self):       
        refId = request.form.get('refId').strip()
        mobileNo = request.form.get('mobileNo').strip()

        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}, mobileNo: {mobileNo}")

        twilioClient = TwilioClient('+14155238886')
        lookupsMobile = twilioClient.lookups(mobileNo)

        error = None
        if not lookupsMobile:
            error = f'מספר הנייד {mobileNo} לא תקין'
        else:
            error = await RefPortalApi.handleUsers.addPendingReferee(refId, mobileNo)

        if not error:
            parsed_url = urlparse(request.base_url)
            registrationUrl = f'{parsed_url.scheme}://{parsed_url.netloc}/registration'
            twilioClient = TwilioClient('+14155238886')
            text = f"נא ללחוץ על הקישור הבא ולעדכן את פרטי השופט:\n\n{registrationUrl}"
            sentWhatsappMessage = await twilioClient.send(toMobile=mobileNo, message=text)

            return f"{datetime.now()} קוד שופט {refId} התווסף כמועמד למערכת"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל ברישום {error}, אנא פנה למנהל המערכת"

    async def registration(self):
        return render_template('registration.html')

    async def registrationSubmit(self):       
        refId = request.form.get('refId').strip()
        refName = request.form.get('refName').strip()
        id = request.form.get('id').strip()
        refPassword = request.form.get('refPassword').strip()        
        originAddress = request.form.get('originAddress').strip()
        reminderInHours = int(request.form.get('reminderInHours').strip())
        timeArrivalInMins = int(request.form.get('timeArrivalInMins').strip())
        
        print(f"refId: {refId}, refName: {refName}, id: {id}")
        result = await self.handleUsers.updateReferee(refId, refName, id, refPassword, None, originAddress, reminderInHours, timeArrivalInMins, None)

        if not result:
            parsed_url = urlparse(request.base_url)
            activationUrl = f'{parsed_url.scheme}://{parsed_url.netloc}/activate'
            
            text = f"נא ללחוץ על הקישור הבא ולאקטב את שופט {refId}:\n\n{activationUrl}"
            sentWhatsappMessage = await self.twilioClient.send(toMobile='+972547799979', message=text)
            
            text = f"{datetime.now()} קוד שופט {refId} נרשם למערכת"
            mobileNo = request.form.get('mobile').strip()
            sentWhatsappMessage = await self.twilioClient.send(toMobile=mobileNo, message=text)

        return result

    async def changePassword(self):
        return render_template('changePassword.html')

    async def changePasswordSubmit(self):       
        refId = request.form.get('refId').strip()
        refPassword = request.form.get('refPassword').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")

        result = self.handleUsers.changeRefereePassword(refId, refPassword)

        text = None
        if result == True:
            text = f"{datetime.now()} קוד שופט {refId} סיסמא עודכנה בהצלחה"
        else:
            text = f"{datetime.now()} קוד שופט {refId} נכשל בשינוי סיסמא, אנא פנה למנהל המערכת"
        
        sentWhatsappMessage = await self.twilioClient.send(toMobile='+972547799979', message=text)
        return text

    async def activate(self):
        return render_template('activate.html')

    async def activateSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = await self.handleUsers.activate(refId)

        if not result:
            return f"{datetime.now()} קוד שופט {refId} שופט הופעל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בהפעלת שופט, אנא פנה למנהל המערכת"

    async def deactivate(self):
        return render_template('deactivate.html')

    async def deactivateSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = self.handleUsers.deactivate(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} שופט בוטל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בביטול שופט, אנא פנה למנהל המערכת"

    async def forceSend(self):
        return render_template('forceSend.html')

    async def forceSendSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = self.handleUsers.forceSend(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} שליחה מחודשת הופעל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בשליחה מחודשת, אנא פנה למנהל המערכת"

    async def refreshLeaguesTables(self):
        return render_template('refreshLeaguesTables.html')

    async def refreshLeaguesTablesSubmit(self):       
        leagueName = request.form.get('leagueName').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"leagueName: {leagueName}")
        
        result = await handleTournaments.refreshLeaguesTables(True, leagueName)

        if result == True:
            return f"{datetime.now()} טבלאות עודכנו בהצלחה"
        else:
            return f"{datetime.now()} טבלאות לא עודכנו, אנא פנה למנהל המערכת"

    async def approveGame(self, refId, gameId):
        self.logger.info(f'approveGame refId: {refId}, gameId: {gameId}')
        result = await handleTournaments.approveGame(refId, gameId)

        if result == True:
            return f"{datetime.now()} המשחק אושר בהצלחה"
        else:
            return f"{datetime.now()} אישור המשחק נכשל, אנא פנה למנהל המערכת"

    async def reloadReferees(self):
        self.handleUsers.writeReferees()
        return f"{datetime.now()} מאגר השופטים נטען מחדש"

    async def incomingWebhook(self):
        current_message_sid = request.form.get('MessageSid')
        original_replied_message_sid = request.form.get('OriginalRepliedMessageSid')
        from_mobile = request.form.get('From')
        to_number = request.form.get('To')
        message_body = request.form.get('Body')

        response = MessagingResponse()

        print(f"Received quick reply from {from_mobile} to {to_number}: '{message_body}'")
        print(f"Original replied message SID: {original_replied_message_sid}")
        print(f"Current reply SID: {current_message_sid}")
        print(f"search for Referee")
        refereeDetail = self.refereesByMobile.get(from_mobile.lstrip('whatsapp:'))
        if not refereeDetail:
            return str(response), 404  # Respond with Twilio XML response

        print(f"Referee={refereeDetail['refId']}")
        
        await self.handleUsers.start24HoursWindow(refereeDetail['refId'], helpers.datetime_to_str(datetime.now()))

        originalTemplate = await self.twilioClient.getOriginalTemplate(refereeDetail, original_replied_message_sid, current_message_sid, message_body)
        if originalTemplate:
            contentSid = originalTemplate['contentSid']
            additionalInfo = originalTemplate['additionalInfo']
            repliedAnswer = originalTemplate['repliedAnswer']
            self.logger.info(f'refId={refereeDetail["refId"]} reply={repliedAnswer}')
            referee_webhook_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}referees/webhook/refId{originalTemplate["refId"]}_{current_message_sid}.json'
            helpers.save_to_file(request.form, referee_webhook_file_path)

            result = None

            if result:
                self.logger.info(f'result={result}')
                response.message(result)

        return str(response), 200  # Respond with Twilio XML response

if __name__ == '__main__':
    refPortalApi = RefPortalApi()
    asyncio.run(refPortalApi.start())
    #asyncio.run(refPortalApi.approveGame('43679', '26396ab6'))