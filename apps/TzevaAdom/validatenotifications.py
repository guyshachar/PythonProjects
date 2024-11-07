import types
import sys
sys.path.append("..")
from Shared.logger import Logger

class ValidateNotifications:
    def __init__(self):
        Logger(self)
        pass

    def validateNotifications(self, notificationsList, citiesToValidate):
        if notificationsList:
            if len(notificationsList) > 0:
                self.logger.debug(f'notificationsList={notificationsList}')
                foundAny = False
                notificationIds = list()
                validatedNotificationsPerGroup = list()
                for vc_group in citiesToValidate:
                    validatedNotifications = list()
                    for n in notificationsList:
                        self.logger.debug(f'validateNotifications n={n}')
                        cities = list()
                        for c in n["cities"]:
                            self.logger.debug(f'validateNotifications c={c}')
                            for vc in vc_group:
                                self.logger.debug(f'validateNotifications vc={vc}')
                                if vc == 'ALL' or vc in c:
                                    foundAny = True
                                    cities.append(c)
                        
                        if len(cities) > 0:
                            notificationIds.append(n["notificationId"])
                            
                        validatedNotifications.append(types.SimpleNamespace(notificationId=n["notificationId"], time=n["time"], cities=cities))
                    validatedNotificationsPerGroup.append(validatedNotifications)
                
                if foundAny:
                    self.logger.debug(f'foundAny={foundAny} {validatedNotificationsPerGroup}')
                
                return types.SimpleNamespace(foundAny=foundAny,notificationIds=list(set(notificationIds)),validatedNotificationsPerGroup=validatedNotificationsPerGroup)
        
        return types.SimpleNamespace(foundAny=False)