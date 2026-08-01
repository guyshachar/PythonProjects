from shared.logger import Logger
from shared.db import CacheService
from shared.db.repositories import TenantRepository
from shared.orgRelated import MultiTenantSupport

class CommonHelper:
    def __init__(self, logger:Logger, multiTenantSupport:MultiTenantSupport, cacheService:CacheService, tenantRepository:TenantRepository=None):
        self.logger = logger
        self.multiTenantSupport = multiTenantSupport
        self.cacheService = cacheService
        self.tenantRepository = tenantRepository

        self.tenants = self.tenantRepository.get_tenants() if tenantRepository else self.cacheService.getTenants()
        pass

    def generateGameRefereeDetails(self, tenantKey, refDetail):
        if not refDetail:
            return ''

        details = ''
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=refDetail, property='role')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=refDetail, property='* name')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=refDetail, property='* status')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=refDetail, property='* level')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=refDetail, property='* phone')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=refDetail, property='* address')
        return details

    def generateGameReferees(self, tenantKey, gameDetail, includeReferees=False, includeReviewer=False):
        referees = gameDetail.get('referees')
        if referees == None or includeReferees == False:
            return ''
        details = ''
        if isinstance(referees, dict):
            referees = list(referees.values())            
        for refDetail in referees:
            if refDetail.get('reviewer', False) == False or (refDetail.get('reviewer', False) == True and includeReviewer):
                details += self.generateGameRefereeDetails(tenantKey=tenantKey, refDetail=refDetail)
        return details
        
    def generateGameDetails(self, tenantKey, gameDetail, includeReferees=False, includeReviewer=False, includeCarpool=False):
        details = ''
        details += f'*{self.tenants[tenantKey].name}*'
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='dateText')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='dow')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='tournamentName')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='gameTitle')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='role')
        if len(gameDetail.get('referees', [])) > 1:
            details += '*'
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='round')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='fixture')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='field', valueProperty='fieldName')
        if includeReferees:
            details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='status')
            details += '\n'
            details += self.generateGameReferees(tenantKey=tenantKey, gameDetail=gameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
        if includeCarpool and gameDetail.get('carpool'):
            details += self._generateCarpoolDetails(gameDetail['carpool'])
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='comment')
        return details

    def _generateCarpoolDetails(self, carpool):
        if not carpool or not carpool.get('cars'):
            return ''
        lines = ['\n\n🚗 *נסיעה משותפת:*']
        for i, car in enumerate(carpool['cars'], 1):
            if len(carpool['cars']) > 1:
                lines.append(f'רכב {i}:')
            driver_name = car.get('driverName') or car.get('driverMobileNo', '')
            lines.append(f'נהג: {driver_name}')
            passengers = car.get('passengers', [])
            if passengers:
                pax_names = ', '.join(p.get('name') or p.get('mobileNo', '') for p in passengers)
                lines.append(f'נוסעים: {pax_names}')
            route = car.get('route')
            if route:
                dur = route.get('totalDurationMinutes', '')
                dist = route.get('totalDistanceKm')
                summary = f'זמן נסיעה: {dur} דקות'
                if dist:
                    summary += f' | {dist} ק"מ'
                lines.append(summary)
                for stop in route.get('stops', []):
                    stop_name = stop.get('name') or stop.get('mobileNo', '')
                    lines.append(f'  📍 {stop_name} — +{stop.get("cumulativeDurationMinutes")} דק\'')
                if route.get('googleMapsUrl'):
                    lines.append(f'🗺️ {route["googleMapsUrl"]}')
        return '\n'.join(lines)

    def generateReviewDetails(self, tenantKey, gameDetail, includeReferees=None, includeReviewer=None):
        details = ''
        details += f'*{self.tenants[tenantKey].name}*'
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='no.')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='dateText')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='timeText')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='tournamentName')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='gameTitle')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='field', valueProperty='fieldName')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='fixture')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='role')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='reviewer')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='reviewGrade')
        return details

    def objProperty(self, tenantKey, objType, obj, property, valueProperty=None, label=None, cr=True):
        countryCode = tenantKey.split('#')[0]
        eventType = tenantKey.split('#')[1]
        label = label or self.multiTenantSupport.reverse_key_mapping[countryCode][eventType][objType].get(property, property)
        propValue = obj.get(valueProperty or property)
        if isinstance(propValue, dict):
            propValue = None
        else:
            propValue = self.multiTenantSupport.reverse_key_mapping[countryCode][eventType][objType].get(propValue, propValue)
        if propValue:
            text = ''
            if cr:
                text = '\n'
            text = f'{text}{label or property}: {propValue}'
            return text
        return ''