from flask import Flask, render_template, request, redirect
import asyncio
import json
import sys
import logging
import socket
import os
from pathlib import Path
from datetime import datetime
# Add the rpService directory to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.handleUsers import addPendingReferee, addReferee, changeRefereePassword, activate, deactivate, forceSend
from shared.handleTournaments import refreshLeaguesTables
import shared.twilioClient as twilioClient

class RefPortalApi():
    app = Flask(__name__)
    twilioClientInstance = twilioClient.TwilioClient('+14155238886')

    def __init__(self):
        openText=f'Ref Portal Api {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        logging.info(openText)

    async def start(self):
        try:
            logging.info('start')
            ssl_file_path = f'{os.getenv("MY_SSL_FILE", "/run/ssl/")}'
            self.app.run(host='0.0.0.0', debug=True, port=5001, ssl_context=(f'{ssl_file_path}cert.pem', f'{ssl_file_path}key.pem'))     
        except Exception as e:
            logging.error(json.dumps(e))
    
    @app.route('/')
    async def welcome(self):
        logging.info('welcome')
        return f'welcome {socket.gethostname()} {datetime.now()}...'
    
    @app.route('/health')
    async def health(self):
        logging.info('health')
        return f'Health is ok {datetime.now()}...'
    
    @app.route('/addPending')
    async def addPending(self):
        return render_template('addPending.html')

    @app.route('/addPendingSubmit', methods=['POST'])
    async def addPendingSubmit(self):       
        refId = request.form.get('refId').strip()
        
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = addPendingReferee(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} התווסף כמועמד למערכת"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל ברישום, אנא פנה למנהל המערכת"

    @app.route('/registration')
    async def registration(self):
        return render_template('registration.html')

    @app.route('/registrationSubmit', methods=['POST'])
    async def registrationSubmit(self):       
        refId = request.form.get('refId').strip()
        refName = request.form.get('refName').strip()
        id = request.form.get('id').strip()
        refPassword = request.form.get('refPassword').strip()
        mobileNo = request.form.get('mobileNo').strip()
        originAddress = request.form.get('originAddress').strip()
        reminderInHours = int(request.form.get('reminderInHours').strip())
        timeArrivalInMins = int(request.form.get('timeArrivalInMins').strip())
        
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}, refName: {refName}, id: {id}, mobileNo: {mobileNo}")
        
        result = addReferee(refId, refName, id, refPassword, mobileNo, originAddress, reminderInHours, timeArrivalInMins)

        text = None
        if result == True:
            text = f"{datetime.now()} קוד שופט {refId} נרשם למערכת"
        else:
            text = f"{datetime.now()} קוד שופט {refId} נכשל ברישום, אנא פנה למנהל המערכת"

        sentWhatsappMessage = await self.twilioClientInstance.send(toMobile='+972547799979', message=text)
        return text

    @app.route('/changePassword')
    async def changePassword(self):
        return render_template('changePassword.html')

    @app.route('/changePasswordSubmit', methods=['POST'])
    async def changePasswordSubmit(self):       
        refId = request.form.get('refId').strip()
        refPassword = request.form.get('refPassword').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = changeRefereePassword(refId, refPassword)

        text = None
        if result == True:
            text = f"{datetime.now()} קוד שופט {refId} סיסמא עודכנה בהצלחה"
        else:
            text = f"{datetime.now()} קוד שופט {refId} נכשל בשינוי סיסמא, אנא פנה למנהל המערכת"
        
        sentWhatsappMessage = await self.twilioClientInstance.send(toMobile='+972547799979', message=text)
        return text

    @app.route('/activate')
    async def activate(self):
        return render_template('activate.html')

    @app.route('/activateSubmit', methods=['POST'])
    async def activateSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = activate(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} שופט הופעל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בהפעלת שופט, אנא פנה למנהל המערכת"

    @app.route('/deactivate')
    async def deactivate(self):
        return render_template('deactivate.html')

    @app.route('/deactivateSubmit', methods=['POST'])
    async def deactivateSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = deactivate(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} שופט בוטל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בביטול שופט, אנא פנה למנהל המערכת"

    @app.route('/forceSend')
    async def forceSend(self):
        return render_template('forceSend.html')

    @app.route('/forceSendSubmit', methods=['POST'])
    async def forceSendSubmit(self):       
        refId = request.form.get('refId').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"refId: {refId}")
        
        result = forceSend(refId)

        if result == True:
            return f"{datetime.now()} קוד שופט {refId} שליחה מחודשת הופעל בהצלחה"
        else:
            return f"{datetime.now()} קוד שופט {refId} נכשל בשליחה מחודשת, אנא פנה למנהל המערכת"

    @app.route('/refreshLeaguesTables')
    async def refreshLeaguesTables(self):
        return render_template('refreshLeaguesTables.html')

    @app.route('/refreshLeaguesTablesSubmit', methods=['POST'])
    async def refreshLeaguesTablesSubmit(self):       
        leagueName = request.form.get('leagueName').strip()
        # Handle the submitted parameters (e.g., print or save them)
        print(f"leagueName: {leagueName}")
        
        result = await refreshLeaguesTables(True, leagueName)

        if result == True:
            return f"{datetime.now()} טבלאות עודכנו בהצלחה"
        else:
            return f"{datetime.now()} טבלאות לא עודכנו, אנא פנה למנהל המערכת"

if __name__ == '__main__':
    refPortalApi = RefPortalApi()
    asyncio.run(refPortalApi.start())