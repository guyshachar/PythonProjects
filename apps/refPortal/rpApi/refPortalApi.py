from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import asyncio
import json
import sys
import logging
import socket
import os
import uuid
from twilio.twiml.messaging_response import MessagingResponse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
# Add the rpService directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.handleUsers import HandleUsers
import shared.handleTournaments as handleTournaments
from shared.twilioClient import TwilioClient
import shared.helpers as helpers
from shared.fileWatcher import watchFileChange

class RefPortalApi():
    def __init__(self):
        # Configure logging
        logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
        logging.basicConfig(level=logLevel, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
        
        self.handleUsers = HandleUsers()

        (self.refereesDetails, self.refereesByMobile) = self.handleUsers.getAllRefereesByMobile()
        
        twilioServiceId = os.environ.get('twilioServiceId')
        self.twilioFromMobile = os.environ.get('twilioFromMobile')
        self.twilioClient = TwilioClient(twilioServiceId=twilioServiceId, fromMobile=self.twilioFromMobile)
        self.twilioOnBoardingAdminMobile = os.environ.get('twilioOnBoardingAdminMobile')

        openText=f'Ref Portal Api {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        self.logger.info(openText)
        
        self.watchFiles()

        self.app = Flask(__name__)
        self.limiter = Limiter(get_remote_address, app=self.app, default_limits=[f'{os.environ.get("limitPerMin")} per minute'])

        self.app.before_request(self.beforeRequestFunc)

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
        self.app.add_url_rule('/api/approveGame/<refId>/<msgSid>/<gameId>', 'approveGame', self.approveGame, methods=['GET'])
        self.app.add_url_rule('/reloadReferees', 'reloadReferees', self.reloadReferees, methods=['GET'])
        self.app.add_url_rule('/incomingWebhook', 'incomingWebhook', self.incomingWebhook, methods=['POST'])
        statusCallBackLimit = self.limiter.exempt()(self.statusCallback)
        self.app.add_url_rule('/api/statusCallback', 'statusCallback', statusCallBackLimit, methods=['POST'])
        downloadIcsFileLimit = self.limiter.limit('10 per minute')(self.downloadIcsFile)
        self.app.add_url_rule('/api/file/<fileId>', 'file', downloadIcsFileLimit, methods=['GET'])

    def getFlaskApp(self):
        return self.app

    async def start(self):
        try:
            self.logger.info('start')
            ssl_file_path = f'{os.getenv("MY_SSL_FILE", "/run/ssl/")}'
            flaskDebug = eval(os.environ.get('flaskDebug') or 'True')
            self.app.run(host='0.0.0.0', debug=flaskDebug, port=5001, ssl_context=(f'{ssl_file_path}cert.pem', f'{ssl_file_path}key.pem'))     
        except Exception as e:
            self.logger.error(json.dumps(e))

    def watchFiles(self):
        try:
            messages_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}messages/messages.json'
            self.messagesFileWatchObserver = watchFileChange(messages_file_path, self.twilioClient.loadMessages)

            self.twilioClient.loadMessages(messages_file_path)

        except Exception as ex:
            self.logger.error(f'watchFiles error: {ex}')

    def beforeRequestFunc(self):
        self.logger.info(f"Intercepted request to: {request.path} from: {get_remote_address()}")

    def downloadIcsFile(self, fileId):
        self.logger.info(f"downloadIcsFile: fileId={fileId}")
        refId = fileId.split('_')[0]
        gameId = fileId.split('_')[1]
        (fileId, icsGameFilename) = helpers.getGameIcsFilename(refId, gameId)
        icsFileExists = os.path.exists(icsGameFilename)
        if not icsFileExists:
            return abort(404)

        return send_file(icsGameFilename, mimetype='text/calendar')
    
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
        self.logger.info(f"refId: {refId}")
        
        result = self.handleUsers.getRefereeDetailByRefId(refId)
        if 'password' in result:
            del result['password']

        if result:
            return f"{result}\n{datetime.now()}"
        else:
            return f"{datetime.now()} קוד שופט {refId} לא נמצא, אנא פנה למנהל המערכת"

    async def askToJoin(self, mobileNo):
        twilioOnBoardingJoinConfirmation = os.environ.get('twilioOnBoardingJoinConfirmation')

        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")

        lookupsMobile = self.twilioClient.lookups(mobileNo)

        error = None
        if not lookupsMobile:
            error = f'מספר הנייד {mobileNo} לא תקין'

        if not error:
            contentVariables = {
                "mobileNo1": mobileNo,
                "mobileNo2": mobileNo
            }
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=lookupsMobile.phone_number, contentSid=twilioOnBoardingJoinConfirmation,contentVariables=contentVariables)
            return f"{datetime.now()} שופט {lookupsMobile.phone_number} נשלחה בקשת הצטרפות"
        else:
            return f"{datetime.now()} שופט {lookupsMobile.phone_number} נכשל בשליחת בקשת הצטרפות {error}, אנא פנה למנהל המערכת"

    async def addPending(self):
        return render_template('addPending.html')

    async def joinConfirmationReply(self, mobileNo, answer):
        twilioOnBoardingRegistration = os.environ.get('twilioOnBoardingRegistration')

        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"mobileNo: {mobileNo}")

        lookupsMobile = self.twilioClient.lookups(mobileNo)

        error = None
        if not lookupsMobile:
            error = f'מספר הנייד {mobileNo} לא תקין'
        elif answer == 'yes':
            error = await self.handleUsers.addPendingReferee(lookupsMobile.phone_number)
        else:
            error = f'מספר הנייד {mobileNo} לא מעוניין להצטרף לשירות'

        if not error:
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=lookupsMobile.phone_number, contentSid=twilioOnBoardingRegistration, contentVariables=None)
            return f"{datetime.now()} שופט {lookupsMobile.phone_number} התווסף כמועמד למערכת"
        else:
            return f"{datetime.now()} שופט {lookupsMobile.phone_number} נכשל ברישום {error}, אנא פנה למנהל המערכת"

    async def addPendingSubmit(self, mobileNo):
        return self.addPendingProcess(mobileNo)
    
    async def registration(self):
        self.logger.info(f"In registration")
        return render_template('registration.html')

    async def registrationSubmit(self):
        twilioOnBoardingActivate = os.environ.get('twilioOnBoardingActivate')

        inputMobileNo = request.form.get('mobileNo').strip()
        if len(inputMobileNo) == 10:
            mobileNo = f'+972{inputMobileNo[1:]}'
        else:
            mobileNo = inputMobileNo
        lookupsMobile = self.twilioClient.lookups(mobileNo)
        result = None
        if not lookupsMobile:
            result = f'מספר הנייד {inputMobileNo} לא תקין (צריך להתחיל ב +972)'
            return result
    
        refId = request.form.get('refId').strip()

        refName = request.form.get('refName').strip()
        id = request.form.get('id').strip()
        refPassword = request.form.get('refPassword').strip()        
        originAddress = request.form.get('originAddress').strip()
        reminderInHours = int(request.form.get('reminderInHours').strip())
        timeArrivalInMins = int(request.form.get('timeArrivalInMins').strip())
        
        self.logger.info(f"refId: {refId}, refName: {refName}, id: {id}, mobile: {mobileNo}")
        result = await self.handleUsers.updateReferee(mobileNo, refId, refName, id, refPassword, None, originAddress, reminderInHours, timeArrivalInMins, None)

        if not result:
            await self.reloadReferees()
            refereeDetail = self.handleUsers.getRefereeDetailByRefId(refId)
            mobileNo = refereeDetail['mobile']
            
            parsed_url = urlparse(request.base_url)
            activationUrl = f'{parsed_url.scheme}://{parsed_url.netloc}/activate'
            
            text = f"נא ללחוץ על הקישור הבא ולאקטב את שופט {refId}:\n\n{activationUrl}"
            contentVariables = {
                "refId": refId,
                "refName": refName
            }
            msgSid = await self.twilioClient.sendUsingContentTemplate(toMobile=self.twilioOnBoardingAdminMobile, contentSid=twilioOnBoardingActivate, contentVariables=contentVariables)
            
            text = f"קוד שופט {refId} נרשם למערכת"
            msgSid = await self.twilioClient.sendFreeText(toMobile=mobileNo, message=text)
            return 'הפרטים עודכנו בהצלחה'

        return result

    async def changePassword(self):
        return render_template('changePassword.html')

    async def changePasswordSubmit(self):       
        refId = request.form.get('refId').strip()
        refPassword = request.form.get('refPassword').strip()
        return await self.changePasswordByRefId(refId, refPassword)

    async def changePasswordByRefId(self, refId, refPassword):       
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"refId: {refId}")

        result = self.handleUsers.changeRefereePassword(refId, refPassword)

        text = None
        if result == True:
            text = f"קוד שופט {refId} סיסמא עודכנה בהצלחה"
        else:
            text = f"קוד שופט {refId} נכשל בשינוי סיסמא, אנא פנה למנהל המערכת"
        
        msgSid = await self.twilioClient.sendFreeText(toMobile=self.twilioOnBoardingAdminMobile, message=text)
        return text

    async def activate(self):
        return render_template('activate.html')

    async def activateByRefId(self, refId):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"refId: {refId}")
        
        result = await self.handleUsers.activate(refId)

        if not result:
            return f"{datetime.now()} קוד שופט {refId} שופט הופעל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בהפעלת שופט, אנא פנה למנהל המערכת"

    async def activateSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        result = self.activateByRefId(refId)
        return result

    async def deactivate(self):
        return render_template('deactivate.html')

    async def deactivateSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"refId: {refId}")
        
        result = self.handleUsers.deactivate(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} שופט בוטל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בביטול שופט, אנא פנה למנהל המערכת"

    async def forceSend(self, refId):
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"refId: {refId}")
        
        result = await self.handleUsers.activate(refId)

        if not result:
            return f"{datetime.now()} קוד שופט {refId} שופט הופעל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בהפעלת שופט, אנא פנה למנהל המערכת"

    async def forceSendByRefId(self, refId, objType = None, msgSid = None):
        self.logger.info(f"refId: {refId}")

        if not msgSid:
            msgSid = str(uuid.uuid4())[:16]
        obj = {}
        obj[msgSid] = {'refId': refId, 'created': datetime.now(), 'action': 'forceSend', 'msgSid': msgSid, 'objType': objType, 'status': 'created'}
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/refId{refId}.json'
        helpers.append_to_file(obj, referee_file_path)
            
        return f"{datetime.now()} הבקשה לשליחה מחודשת התקבלה בהצלחה"

    async def forceSendSubmit(self):       
        refId = request.form.get('refId').strip()
        return self.forceSendByRefId(refId)

    async def refreshLeaguesTables(self):
        return render_template('refreshLeaguesTables.html')

    async def refreshLeaguesTablesSubmit(self):       
        leagueName = request.form.get('leagueName').strip()
        # Handle the submitted parameters (e.g., print or save them)
        self.logger.info(f"leagueName: {leagueName}")
        
        result = await handleTournaments.refreshLeaguesTables(True, leagueName)

        if result == True:
            return f"{datetime.now()} טבלאות עודכנו בהצלחה"
        else:
            return f"{datetime.now()} טבלאות לא עודכנו, אנא פנה למנהל המערכת"

    async def approveGame(self, refId, msgSid, gameId):
        self.logger.info(f'approveGame refId: {refId}, gameId: {gameId}')

        obj = {}
        obj[msgSid] = {'refId': refId, 'created': datetime.now(), 'action': 'approveGame', 'msgSid': msgSid, 'gameId': gameId, 'status': 'created'}
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/templates/refId{refId}.json'
        helpers.append_to_file(obj, referee_file_path)
    
        return f"{datetime.now()} הבקשה לאישור המשחק התקבלה בהצלחה"

    async def reloadReferees(self):
        (self.refereesDetails, self.refereesByMobile) = self.handleUsers.getAllRefereesByMobile()
        self.handleUsers.writeReferees()
        return f"{datetime.now()} מאגר השופטים נטען מחדש"

    async def incomingWebhook(self):
        current_message_sid = request.form.get('MessageSid')
        original_replied_message_sid = request.form.get('OriginalRepliedMessageSid')
        from_mobile = request.form.get('From')
        fromMobileNo = from_mobile.lstrip('whatsapp:')
        to_number = request.form.get('To')
        message_body = request.form.get('Body')
        button_id = request.form.get('ButtonPayload')

        response = MessagingResponse()
        #response.message('טקסט לא מזוהה')

        self.logger.info(f"Received quick reply from {from_mobile} to {to_number}: {button_id} '{message_body}'")
        self.logger.info(f"Original replied message SID: {original_replied_message_sid}")
        self.logger.info(f"Current reply SID: {current_message_sid}")
        self.logger.info(f"search for Referee")
        
        refereeDetail = self.refereesByMobile.get(fromMobileNo)
        if refereeDetail:
            referee_webhook_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}referees/webhook/refId{refereeDetail["refId"]}_{current_message_sid}.json'
            helpers.save_to_file(request.form, referee_webhook_file_path)

        # Join Confirmation reply by Referee
        if button_id and button_id.lower().startswith('joinconfirmation_'):
            answer = button_id.split('_')[1]
            mobileNo = button_id.split('_')[2]
            result = await self.joinConfirmationReply(mobileNo, answer)
            response.message(result)

        # Request to Approve Game by Referee
        elif button_id and button_id.lower().startswith('approvegameid_') and refereeDetail:
            gameId = button_id.split('_')[1]
            result = await self.approveGame(refereeDetail['refId'], current_message_sid, gameId)
            response.message(result)

        # Request to Update Password by Referee
        elif message_body and message_body.lower().startswith('updatepassword_') and refereeDetail:
            refPassword = message_body.split('_')[1]
            result = await self.changePasswordByRefId(refereeDetail['refId'], refPassword)
            response.message(result)

        elif fromMobileNo == self.twilioOnBoardingAdminMobile:
            # Ask to Join new Referee by Admin
            if message_body and message_body.lower().startswith('asktojoin_'):
                mobileNo = message_body.split('_')[1]
                result = await self.askToJoin(mobileNo)
                response.message(result)

            # Activate Referee by Admin
            elif button_id and button_id.lower().startswith('activateref_'):
                refId = button_id.split('_')[1]
                result = await self.activateByRefId(refId)
                response.message(result)

            # Force Send games/reviews messages to Referee by Admin
            elif button_id and button_id.lower().startswith('forcesend'):
                objType = None
                refId = button_id.split('_')[1]
                if len(button_id.split('_')) > 2:
                    objType = button_id.split('_')[2]
                result = await self.forceSendByRefId(refId, objType, current_message_sid)
                response.message(result)
            elif message_body == 'חדש רישום':
                pass
            else:
                response.message('טקסט לא מזוהה')
        elif message_body == 'חדש רישום':
            pass
        else:
            response.message('טקסט לא מזוהה')

        return str(response), 200  # Respond with Twilio XML response

    async def statusCallback(self):
        # Get the POST data sent by Twilio
        data = request.form
        messageSid = data.get('MessageSid')
        messageStatus = data.get('MessageStatus')
        errorCode = data.get('ErrorCode')

        response = MessagingResponse()

        self.logger.info(f"Received status update for Message SID: {messageSid} with status: {messageStatus} error code: {errorCode}")
        
        return str(response), 200  # Respond with Twilio XML response

refPortalApi = RefPortalApi()
#app13 = refPortalApi.getFlaskApp()

if __name__ == '__main__':
    asyncio.run(refPortalApi.start())
    #asyncio.run(refPortalApi.approveGame('43679', '26396ab6'))
"""
    flow 
        #1 send askToJoin_+972
        #2 IncomingWebhook - When message received the message
                Create user using MobileNo as LoginId
                Send template message to referee with JoiningConfirmation_+972...  (open 24hrs window)
        #3 IncomingWebhook - When message received send Registration message with link to registration page
        #4 When registration submitted - Create user and delete mobile user
"""
    