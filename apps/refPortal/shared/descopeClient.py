from descope import (
    REFRESH_SESSION_TOKEN_NAME,
    SESSION_TOKEN_NAME,
    AuthException,
    DeliveryMethod,
    DescopeClient,
    AssociatedTenant,
    RoleMapping,
    AttributeMapping
)
from pathlib import Path
import logging
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import json
import os
import logging

class MyDescopeClient():
    def __init__(self, projectId):
        self.logger = logging.getLogger(__name__)

        try:
            descope_mgmt_key = helpers.get_secret('descope_mgmt_key')
            logging.getLogger("twilio").setLevel(logging.WARNING)
            self.descopeClient = DescopeClient(project_id=projectId, management_key=descope_mgmt_key)
        finally:
            pass

    def addReferee(self, refereeDetail):
        role_names=["RefereeRole"]
        user_tenants=[AssociatedTenant("TestTenant")]
        picture = "xxxx"

        if refereeDetail.get('reminders'):
            refereeDetail['reminders'] = list(map(str, refereeDetail.get('reminders')))
        if refereeDetail.get('addressDetails'):      
            refereeDetail['originAddress'] = json.dumps(refereeDetail['addressDetails'])

        try:
            resp = self.descopeClient.mgmt.user.create(
                login_id=refereeDetail["refId"],
                display_name=refereeDetail.get("name"),
                phone=refereeDetail.get("mobile"),
                # You can update user_tenants or role_names, not both in the same action
                #user_tenants=user_tenants,
                role_names=role_names,
                #picture=picture,
                custom_attributes=refereeDetail,
                verified_phone=True
            )
            print ("Successfully created user.")
            print(json.dumps(resp, indent=4))
        except Exception as error:
            print ("Unable to create user.")
            print ("Status Code: " + str(error.status_code))
            print ("Error: " + str(error.error_message))

    def updateReferee(self, refereeDetail):
        role_names=["RefereeRole"]
        user_tenants=[AssociatedTenant("TestTenant")]
        picture = "xxxx"

        if refereeDetail.get('reminders'):
            refereeDetail['reminders'] = list(map(str, refereeDetail['reminders']))
        if refereeDetail.get('addressDetails'):
            refereeDetail['originAddress'] = json.dumps(refereeDetail['addressDetails'])
        # A user must have a login ID, other fields are optional. Roles should be set directly if no tenants exist, otherwise set on a per-tenant basis.
        for i in range(2):
            try:
                action = self.descopeClient.mgmt.user.update
                if i == 1:
                    action = self.descopeClient.mgmt.user.create
                resp = action(
                    login_id=refereeDetail["refId"],
                    display_name=refereeDetail.get("name"),
                    phone=refereeDetail["mobile"],
                    # You can update user_tenants or role_names, not both in the same action
                    #user_tenants=user_tenants,
                    role_names=role_names,
                    #picture=picture,
                    custom_attributes=refereeDetail,
                    verified_phone=True
                )
                print (f"Successfully updated#{i} user {refereeDetail['refId']}.")
                if resp:
                    print(json.dumps(resp, indent=4))
                break
            except Exception as ex:
                print (f"Unable to update user {refereeDetail['refId']}.")
                print ("Status Code: " + str(ex.status_code))
                print ("Error: " + str(ex.error_message))

    def deleteUser(self, loginId):
        user = self.getRefereeDetailByRefId(loginId)
        if user:
            self.descopeClient.mgmt.user.delete(login_id=loginId)

    def addReferees(self):
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/details/refereesDetails.json'
        referees = helpers.load_from_file(referee_file_path)
        for referee in referees:
            refereeDetail = referees[referee]
            self.addReferee(refereeDetail=refereeDetail)

    def updateReferees(self):
        referee_file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}referees/details/refereesDetails.json'
        referees = helpers.load_from_file(referee_file_path)
        for referee in referees:
            refereeDetail = referees[referee]
            refereeDetail['windowStartDatetime'] = None
            self.updateReferee(refereeDetail=refereeDetail)

    def getRefereeDetailByRefId(self, refId):
        referee = self.descopeClient.mgmt.user.search_all(login_ids=[refId])
        if referee['total'] == 1:
            return referee['users'][0]['customAttributes']
        return None

    def getRefereeDetailByMobile(self, mobileNo):
        referee = self.descopeClient.mgmt.user.search_all(phones=[mobileNo])
        if referee['total'] == 1:
            return referee['users'][0]['customAttributes']
        return None

    def searchRefereesDetails(self):
        referees = self.descopeClient.mgmt.user.search_all()
        return referees['users']
   
    def updatePassword(self, refId, password):
        referee = self.getRefereeDetailByRefId(refId)
        self.descopeClient.password.update(refId, password, None)

# Example usage
if __name__ == "__main__":
    try:
        # You can configure the baseURL by setting the env variable Ex: export DESCOPE_BASE_URI="https://auth.company.com  - this is useful when you utilize CNAME within your Descope project."
        #descope_client = DescopeClient(project_id='P2rMfchUiS31ARASEQsuEuf08UME', management_key=management_key)
        descopeClient = MyDescopeClient('P2rMfchUiS31ARASEQsuEuf08UME')
        #descopeClient.updateReferees() 
        #ref = descopeClient.searcRefereeDetail()
        #descopeClient.updateReferees()
        ref = descopeClient.getRefereeDetailByRefId('43679')
        descopeClient.getRefereeDetailByMobile('+972547799979')
        pass
    except Exception as error:
        # handle the error
        print ("failed to initialize. Error:")
        print (error)
