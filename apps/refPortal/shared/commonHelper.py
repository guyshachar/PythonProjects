from shared.logger import Logger
from shared.db import CacheService
from shared.orgRelated import MultiTenantSupport

class CommonHelper:
    def __init__(self, logger:Logger, multiTenantSupport:MultiTenantSupport, cacheService:CacheService):
        self.logger = logger
        self.multiTenantSupport = multiTenantSupport
        self.cacheService = cacheService

        self.tenants = self.cacheService.getTenants()

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
        
    def generateGameDetails(self, tenantKey, gameDetail, includeReferees=False, includeReviewer=False):
        details = ''
        details += f'*{self.tenants[tenantKey].get('name')}*'
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='dateText')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='dow')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='tournamentName')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='gameTitle')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='role')
        if len(gameDetail.get('referees', [])) > 1:
            details += '*'
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='round')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='fixture')
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='field')
        if includeReferees:
            details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='status')
            details += '\n'
            details += self.generateGameReferees(tenantKey=tenantKey, gameDetail=gameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
        details += self.objProperty(tenantKey=tenantKey, objType='games', obj=gameDetail, property='comment')
        return details

    def generateReviewDetails(self, tenantKey, gameDetail, includeReferees=None, includeReviewer=None):
        details = ''
        details += f'*{self.tenants[tenantKey].get('name')}*'
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='no.')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='dateText')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='timeText')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='tournamentName')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='gameTitle')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='field')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='fixture')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='role')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='reviewer')
        details += self.objProperty(tenantKey=tenantKey, objType='reviews', obj=gameDetail, property='reviewGrade')
        return details

    def objProperty(self, tenantKey, objType, obj, property, label=None, cr=True):
        countryCode = tenantKey.split('#')[0]
        eventType = tenantKey.split('#')[1]
        label = label or self.multiTenantSupport.reverse_key_mapping[countryCode][eventType][objType].get(property, property)
        propValue = obj.get(property)
        propValue = self.multiTenantSupport.reverse_key_mapping[countryCode][eventType][objType].get(propValue, propValue)
        if propValue:
            text = ''
            if cr:
                text = '\n'
            text = f'{text}{label or property}: {propValue}'
            return text
        return ''