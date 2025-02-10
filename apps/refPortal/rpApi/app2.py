from flask import Flask
import os
import json

class RefPortalApi():
    def __init__(self):
        print('__init__')
        self.app = Flask(__name__)
        self.app.add_url_rule('/', 'root', self.home, methods=['GET'])
        print('__init__end')

    def home(self):
        print('home')
        return "Hello, Gunicorn23!"

    def start(self):
        try:
            print('start')
            self.app.run()#host='0.0.0.0', debug=flaskDebug, port=5001, ssl_context=(f'{ssl_file_path}cert.pem', f'{ssl_file_path}key.pem'))     
        except Exception as e:
            print(json.dumps(e))

    def getFlaskApp(self):
        return self.app
    
print('Load')
refPortalApi = RefPortalApi()
app13 = refPortalApi.getFlaskApp()

if __name__ == "__main__":
    print('Call start')
    refPortalApi.start()  # Not needed for Gunicorn
