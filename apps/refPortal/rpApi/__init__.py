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
        
        print('create app')
        self.app = Flask(__name__)
        self.limiter = Limiter(self.home, app=self.app, default_limits=[f'{os.environ.get("limitPerMin")} per minute'])

        self.app.before_request(self.beforeFunc)

        self.app.add_url_rule('/', 'root', self.home, methods=['GET'])

    def getFlaskApp(self):
        print('getFlaskApp')
        return self.app

    def start(self):
        try:
            print('start')            
            self.logger.info('start')
            ssl_file_path = f'{os.getenv("MY_SSL_FILE", "/run/ssl/")}'
            flaskDebug = eval(os.environ.get('flaskDebug') or 'True')
            self.app.run()#host='0.0.0.0', debug=flaskDebug, port=5001, ssl_context=(f'{ssl_file_path}cert.pem', f'{ssl_file_path}key.pem'))     
        except Exception as e:
            self.logger.error(json.dumps(e))

    def beforeRequestFunc(self):
        self.logger.info(f"Intercepted request to: {request.path} from: {get_remote_address()}")

    def beforeFunc(self):
        print('home')
        return "Hello, Gunicorn12!"

    def home(self):
        print('home')
        return "Hello, Gunicorn23!"

print('Load')
refPortalApi = RefPortalApi()
app13 = refPortalApi.getFlaskApp()

if __name__ == '__main__':
    print('Call start')
    refPortalApi.start()
