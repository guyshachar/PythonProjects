import types
import sys
sys.path.append("..")
from shared.logger import Logger

def validateNotifications(redAlerts, citiesToValidate, logger):
    if redAlerts:
        logger.debug(f'redAlerts={redAlerts}')
        foundAny = False
        notificationIds = list()
        validatedCitiesPerGroup = list()
        for vc_group in citiesToValidate:
            cities = list()
            for city in redAlerts["data"]:
                logger.debug(f'validateNotifications c={city}')
                for vc in vc_group:
                    logger.debug(f'validateNotifications vc={vc}')
                    if vc == 'ALL' or vc in city:
                        foundAny = True
                        cities.append(city)
            
            citiesStr = ','.join(cities)
            validatedCitiesPerGroup.append({"cities": cities, "citiesStr": citiesStr})

        if foundAny:
            logger.debug(f'foundAny={foundAny} {validatedCitiesPerGroup}')

        result = types.SimpleNamespace(foundAny=foundAny, id=redAlerts["id"], timestamp=redAlerts["timestamp"], validatedCities=validatedCitiesPerGroup, title=redAlerts["title"] ,desc=redAlerts["desc"], time_to_run=redAlerts["time_to_run"])
        
        return result
    
    text = types.SimpleNamespace(foundAny=False)
    return text