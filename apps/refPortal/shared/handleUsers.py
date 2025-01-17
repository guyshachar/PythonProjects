from cryptography.fernet import Fernet
import json
import os
import sys
from pathlib import Path
import logging
import socket
from datetime import datetime
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
from shared.twilioClient import TwilioClient
from shared.descopeClient import MyDescopeClient

class HandleUsers():
    def __init__(self):
        openText=f'Ref Portal Api {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} build#{os.environ.get("BUILD_DATE")} host={socket.gethostname()}'
        self.descopeClient = MyDescopeClient('P2rMfchUiS31ARASEQsuEuf08UME')
        logging.info(openText)

    def refereeFilePath(self):
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/details/referees.json'
        return referee_file_path

    def readReferees(self):
        referees = []
        referees = self.getAllRefereesDetails()
        return referees

    def writeReferees(self):
        referee_file_path = self.refereeFilePath()
        referees = helpers.load_from_file(referee_file_path)
        helpers.save_to_file(referees, referee_file_path)

    def encrypt(self, referees):
        key = Fernet.generate_key()
        with open("secret/password_key", "wb") as key_file:
            key_file.write(key)

        # Load the key
        with open("secret/password_key", "rb") as key_file:
            key = key_file.read()

        fernet = Fernet(key)
        
        for referee in referees:
            password = referees[referee]
            encodedPassword = password.encode()
            encryptedPassword = fernet.encrypt(encodedPassword).decode("utf-8")
            referees[referee] = encryptedPassword
            print(f'{password} {encryptedPassword}')

    def encryptPassword(self, password):
        key = helpers.get_secret('password_key')
        fernet = Fernet(key)
        encodedPassword = password.encode()
        encryptedPassword = fernet.encrypt(encodedPassword).decode("utf-8")
        return encryptedPassword

    def decryptPassword(self, password):
        key = helpers.get_secret('password_key')
        fernet = Fernet(key)
        decryptedPassword = fernet.decrypt(password).decode()
        return decryptedPassword

    def changeRefereePassword(self, refId, refPassword):
        refereeDetail = self.getRefereeDetail(refId)

        encryptedPassword = self.encryptPassword(f'{refPassword}')

        refereeDetail['password'] = encryptedPassword

        self.descopeClient.updateReferee(refereeDetail)

        self.writeReferees()

        return True

    def forceSend(self, refId):
        refereeDetail = self.getRefereeDetail(refId)
        refereeDetail['forceSend'] = True
        self.writeReferees()

    async def activate(self, refId):
        refereeDetail = self.getRefereeDetail(refId)
        refereeDetail['status'] = 'active'
        self.descopeClient.updateReferee(refereeDetail)
        self.writeReferees()

    async def deactivate(self, refId):
        refereeDetail = self.getRefereeDetail(refId)
        refereeDetail['status'] = 'inactive'
        self.descopeClient.updateReferee(refereeDetail)
        self.writeReferees()

    def getRefereeDetail(self, refId):
        refereeDetail = self.descopeClient.getRefereeDetail(refId)
        refereeDetail['addressDetails'] = json.loads(refereeDetail['originAddress'])
        return refereeDetail

    def getAllRefereesDetails(self):
        referees = self.descopeClient.searchRefereesDetails()
        referesDetails = {}
        for referee in referees:
            refereeDetail = referee['customAttributes']
            refereeDetail['addressDetails'] = json.loads(refereeDetail['originAddress'])
            referesDetails[refereeDetail['refId']] = refereeDetail
        return referesDetails

    async def addPendingReferee(self, refId, mobileNo, baseUrl):
        refereeDetail = self.getRefereeDetail(refId)
        if refereeDetail:
            refereeDetail['status'] = 'pending'
            self.descopeClient.updateReferee(refereeDetail)
        else:
            refereeDetail = {
                "refId": refId,
                "status": "pending",
                "mobile": mobileNo
            }
            self.descopeClient.addReferee(refereeDetail)

        self.writeReferees()

        return None

    async def addReferee(self, refId, name, id, refPassword, mobile, address, lastNoticeBeforeGameInHours, timeArrivalInMin, color=None):
        refereeDetail = self.getRefereeDetail(refId)
        if refereeDetail:
            return f''
        
        mobile = mobile.replace('-','')
        mobile = mobile.replace(' ','')
        
        if not color:
            color = "LIGHTWHITE_EX"
        
        encryptedPassword = self.encryptPassword(f'{refPassword}')
        coordinates, formattedAddress, error = helpers.get_coordinates_google_maps(f'{address}')
        if not coordinates:
            coordinates = [None, None]

        refereeDetail = {
            "name": name,
            "refId": refId,
            "id": id,
            "mobile": mobile,
            "objTypes": [
                "games",
                "reviews"
            ],
            "reminders": [
                24,
                int(lastNoticeBeforeGameInHours)
            ],
            "timeArrivalInAdvance": int(timeArrivalInMin),
            "color": color,
            "status": "pending",
            "addressDetails": {
                "address": address,
                "coordinates": {
                    "lat": coordinates[0],
                    "lng": coordinates[1]
                },
                "formattedAddress": formattedAddress
            },
            "password": encryptedPassword
        }

        self.descopeClient.addReferee(refereeDetail)
        self.writeReferees()
        return None

    async def updateReferee(self, refId, name, id, refPassword, mobileNo, address, lastNoticeBeforeGameInHours, timeArrivalInMin, color):
        refereeDetail = self.getRefereeDetail(refId)
        text = None
        if not refereeDetail:
            text = f"{datetime.now()} קוד שופט {refId} נכשל ברישום, אנא פנה למנהל המערכת"
        else:
            status = refereeDetail['status']
            if not status or status != 'pending':
                return f'לא מורשה להצטרף למערכת'
            
            if mobileNo:
                mobileNo = mobileNo.replace('-','')
                mobileNo = mobileNo.replace(' ','')
            else:
                mobileNo = refereeDetail['mobile']
            
            if not color:
                color = "LIGHTWHITE_EX"
            
            encryptedPassword = self.encryptPassword(f'{refPassword}')
            coordinates, formattedAddress, error = helpers.get_coordinates_google_maps(f'{address}')
            if not coordinates:
                coordinates = [None, None]

            refereeDetail = {
                "name": name,
                "refId": refId,
                "id": id,
                "mobile": mobileNo,
                "objTypes": [
                    "games",
                    "reviews"
                ],
                "reminders": [
                    24,
                    int(lastNoticeBeforeGameInHours)
                ],
                "timeArrivalInAdvance": int(timeArrivalInMin),
                "color": color,
                "status": status,
                "addressDetails": {
                    "address": address,
                    "coordinates": {
                        "lat": coordinates[0],
                        "lng": coordinates[1]
                    },
                    "formattedAddress": formattedAddress
                },
                "password": encryptedPassword
            }

            self.descopeClient.updateReferee(refereeDetail)
            self.writeReferees()
        
        return text

    async def start24HoursWindow(self, refId, windowStartDatetime):
        refereeDetail = self.getRefereeDetail(refId)
        if not refereeDetail:
            return False

        refereeDetail['windowStartDatetime'] = windowStartDatetime
        self.descopeClient.updateReferee(refereeDetail)
        self.writeReferees()
        
        return True

    def verifyMobile(self, mobileNo):
        client = TwilioClient('+14155238886')

        # Lookup API call
        lookup = client.lookups(mobileNo)

        print(f"Carrier: {lookup.carrier}")
        print(f"Phone Type: {lookup.carrier['type']}")

if __name__ == "__main__":
    pass
#    referees = readReferees()
#    passwords = readPasswords()
#    mergeReferees(referees, passwords)
#    writeReferees(referees)
    #encrypt(referees)
    #writePasswords(referees)
#    for referee in referees:
#        decryptedPassword = decryptPassword(referees[referee])
#        print(decryptedPassword)
    #encryptedPassword = encryptPassword('aaaaaaaaaaa')
    #print(encryptedPassword)

    #addReferee()
    #updatePassword()
    #verifyMobile("+972506809242")
    #cleanupfile()