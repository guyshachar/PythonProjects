from flask import Flask, render_template, request, redirect
import asyncio
import sys
import os
import logging
import socket
from pathlib import Path
from datetime import datetime

class WebTest():
    app = Flask(__name__)

    def __init__(self):
        logging.info('init')
        pass

    async def start(self):
        logging.info('start')
        ssl_file_path = f'{os.getenv("MY_SSL_FILE", "/run/ssl/")}'
        self.app.run(host='0.0.0.0', debug=True, port=5002, ssl_context=(f'{ssl_file_path}cert.pem', f'{ssl_file_path}key.pem'))     

    @app.route('/')
    async def welcome(self):
        logging.info('welcome')
        return f'welcome {socket.gethostname()} {datetime.now()}...'
    
    @app.route('/health')
    async def test(self):
        logging.info('health')
        return f'Health is ok {datetime.now()}...'

if __name__ == '__main__':
    webTestApp = WebTest()
    asyncio.run(webTestApp.start())