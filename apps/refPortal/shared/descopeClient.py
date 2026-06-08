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
from datetime import datetime, timedelta
import json
import os
import logging
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger

class MyDescopeClient():
    def __init__(self, logger:Logger, projectId):
        self.logger = logger
        self.tenantId = os.getenv('countryCode') + '-' + os.getenv('eventType')

        descopeLogger = logging.getLogger("descope")
        descopeLogger.setLevel(logging.CRITICAL)
        descopeLogger.propagate = False

        try:
            descope_mgmt_key = helpers.get_secret('descope_mgmt_key')
            self.descopeClient = DescopeClient(project_id=projectId, management_key=descope_mgmt_key)

            self.logger.info(f'MyDescopeClient starts...')    
        finally:
            pass

    def addReferee(self, refereeDetail):
        role_names=["RefereeRole"]
        #user_tenants=[AssociatedTenant("TestTenant")]
        user_tenants=[AssociatedTenant(tenant_id=self.tenantId, role_names=role_names)]
        picture = "xxxx"

        if refereeDetail.get('reminders'):
            refereeDetail['reminders'] = list(map(str, refereeDetail.get('reminders')))
        if refereeDetail.get('addressDetails'):      
            refereeDetail['originAddress'] = json.dumps(refereeDetail['addressDetails'])
        refereeDetail['updateDatetime'] = helpers.localNow().isoformat()

        try:
            resp = self.descopeClient.mgmt.user.create(
                user_tenants=user_tenants,
                login_id=refereeDetail["mobile"],
                display_name=refereeDetail.get("name"),
                phone=refereeDetail.get("mobile"),
                # You can update user_tenants or role_names, not both in the same action
                #user_tenants=user_tenants,
                role_names=role_names,
                #picture=picture,
                custom_attributes=refereeDetail,
                verified_phone=True,
            )
            self.logger.debug ("Successfully created user.")
            self.logger.debug(json.dumps(resp, indent=4))
        except Exception as error:
            self.logger.debug ("Unable to create user.")
            self.logger.debug ("Status Code: " + str(error.status_code))
            self.logger.debug ("Error: " + str(error.error_message))

    def updateReferee(self, refereeDetail):
        role_names=["RefereeRole"]
        user_tenants=[AssociatedTenant(tenant_id=self.tenantId, role_names=role_names)]

        if refereeDetail.get('reminders'):
            refereeDetail['reminders'] = list(map(str, refereeDetail['reminders']))
        if refereeDetail.get('addressDetails'):
            refereeDetail['originAddress'] = json.dumps(refereeDetail['addressDetails'])
        refereeDetail['updateDatetime'] = helpers.localNow().isoformat()
        # A user must have a login ID, other fields are optional. Roles should be set directly if no tenants exist, otherwise set on a per-tenant basis.
        for i in range(2):
            try:
                action = self.descopeClient.mgmt.user.update
                if i == 1:
                    action = self.descopeClient.mgmt.user.create
                resp = action(
                    user_tenants=user_tenants,
                    login_id=refereeDetail["mobile"],
                    display_name=refereeDetail.get("name"),
                    phone=refereeDetail["mobile"],
                    # You can update user_tenants or role_names, not both in the same action
                    #user_tenants=user_tenants,
                    role_names=role_names,
                    #picture=picture,
                    custom_attributes=refereeDetail,
                    verified_phone=True
                )
                self.logger.info (f"Successfully updated#{i} user {refereeDetail['refId']}.")
                if resp:
                    self.logger.debug(json.dumps(resp, indent=4))
                break
            except Exception as ex:
                self.logger.error('updateReferee', ex)

    def deleteUser(self, loginId):
        user = self.getRefereeDetailByMobile(loginId)
        if user:
            self.descopeClient.mgmt.user.delete(login_id=loginId)

    def addReferees(self):
        referee_file_path = f'{os.getenv("MY_DATA_FOLDER", f"/run/data/")}referees/details/refereesDetails.json'
        referees = jsonHelper.load_from_file(referee_file_path)
        for referee in referees:
            refereeDetail = referees[referee]
            self.addReferee(refereeDetail=refereeDetail)

    def updateReferees(self):
        referee_file_path = f'{os.getenv("MY_DATA_FOLDER", f"/run/data/")}referees/details/refereesDetails.json'
        referees = jsonHelper.load_from_file(referee_file_path)
        for referee in referees:
            refereeDetail = referees[referee]
            refereeDetail['windowStartDatetime'] = None
            self.updateReferee(refereeDetail=refereeDetail)

    def getRefereeDetailByRefId(self, refId):
        referee = self.descopeClient.mgmt.user.search_all(tenant_ids=[self.tenantId], custom_attributes={'refId': refId})
        if referee['total'] == 1:
            return referee['users'][0]['customAttributes']
        return None

    def getRefereeDetailByMobile(self, mobileNo):
        referee = self.descopeClient.mgmt.user.search_all(tenant_ids=[self.tenantId], phones=[mobileNo])
        if referee['total'] == 1:
            return referee['users'][0]['customAttributes']
        return None

    def searchRefereesDetails(self):
        try:
            referees = self.descopeClient.mgmt.user.search_all(tenant_ids=[self.tenantId])
            return referees['users']
        except Exception as ex:
            self.logger.error('searchRefereesDetails', ex)

    def updatePassword(self, refId, password):
        referee = self.getRefereeDetailByRefId(refId)
        self.descopeClient.password.update(refId, password, None)

# Example usage
if __name__ == "__main__":
    try:
        # You can configure the baseURL by setting the env variable Ex: export DESCOPE_BASE_URI="https://auth.company.com  - this is useful when you utilize CNAME within your Descope project."
        #descope_client = DescopeClient(project_id='P2rMfchUiS31ARASEQsuEuf08UME', management_key=management_key)
        descopeClient = MyDescopeClient(logging, 'P2rMfchUiS31ARASEQsuEuf08UME')
        result = descopeClient.getRefereeDetailByMobile()
        for referee in result:
            referee['mobile'] = referee['phone']
            referee['identifier'] = referee['phone']
            referee['loginIds'] = [referee['identifier']]
            descopeClient.addReferee(referee)
        jsonHelper.save_to_file(result[:1], 'refereesDetails.json')
        pass
        #descopeClient.deleteUser('43679')
        #ref = descopeClient.getRefereeDetailByRefId('43679')#'43679')        
        ref = {
            "refId": "43679",
            "name": "גיא שחר",
            "mobile": "+972547799979",
            "status": "inactive"
        }
        descopeClient.addReferee(ref)
        descopeClient.getRefereeDetailByRefId()
        #descopeClient.updateReferees() 
        #ref = descopeClient.searcRefereeDetail()
        #descopeClient.updateReferees()
        #descopeClient.getRefereeDetailByMobile('+972547799979')
        print(ref['test'])
        print(ref['gender'])
        print(ref['isAndroid'])
        pass
    except Exception as error:
        # handle the error
        print ("failed to initialize. Error:")
        print (error)
