import logging
import redis
import sys
import os
import hashlib
import json
from datetime import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from .dbClientBase import DbClientBase
from shared.logger import Logger

class RedisClient(DbClientBase):
    def __init__(self, env, logger:Logger, client:redis.Redis, countryCode, eventType:str, season:str):
        try:
            super().__init__(env, logger, None, countryCode, eventType, season)
            self.client = client
            #self.setDb(db)

            self.logger.info(f'Redis Client starts... Country: {countryCode}, Event: {eventType}')

        except Exception as ex:
            self.logger.error(f'Error in dbClient init:', ex)

    def setDb(self, db):
        self.client.select(db)

    def set(self, key, value, expiry=None, jsonDumps=True):
        try:
            if isinstance(value, dict):
                now = helpers.localNow()
                value['created'] = value.get('created') or now
                value['updated'] = now
                # Add tenant metadata
                value['countryCode'] = self.countryCode
                value['eventType'] = self.eventType
            
            if jsonDumps:
                value = jsonHelper.save_to_json(value)
            
            # Create tenant-aware key
            tenant_key = f"{self.countryCode}#{self.eventType}"
            self.client.set(f'{self.env}:{tenant_key}:{key}', value)
        except Exception as ex:
            pass

    def get(self, keyPrefix, pk=None, jsonDumps=True):
        try:
            key = keyPrefix
            if pk:
                key = f'{key}:{pk}'            
            
            # Create tenant-aware key
            tenant_key = f"{self.countryCode}#{self.eventType}"
            value = self.client.get(f'{self.env}:{tenant_key}:{key}')
            if value and jsonDumps:
                value = jsonHelper.load_from_json(value)
            return value
        except Exception as ex:
            pass

    def getTenantKey(self, season=None):
        """Create tenant-aware partition key"""
        return f"{self.countryCode}#{self.eventType}#{season or self.season}"
    
    def getEntityKey(self, entity_type, entity_id):
        """Create sort key for entity"""
        return f"{entity_type}#{entity_id}"

    def setDict(self, keyPrefix, data):
        if isinstance(data, dict):
            for pk in data:
                row = data[pk]
                self.set(f'{keyPrefix}:{pk}', row)

    def getDict(self, keyPrefix, pk=None, jsonDumps=True):
        try:
            key = keyPrefix
            if pk:
                key = f'{key}:{pk}'            

            cursor = 0
            keys = []

            # Create tenant-aware pattern
            tenant_key = f"{self.countryCode}#{self.eventType}"
            pattern = f'{self.env}:{tenant_key}:{key}:*'

            while True:
                cursor, partial_keys = self.client.scan(cursor, match=pattern, count=500)  # Adjust count as needed
                keys.extend(partial_keys)
                if cursor == 0:  # When cursor reaches 0, iteration is complete
                    break

            dict = {}
            for iterKey in keys:
                if keyPrefix.find('*') > -1:
                    # Remove tenant prefix to get the actual key
                    tenant_prefix = f'{self.env}:{tenant_key}:'
                    pk = iterKey[len(tenant_prefix):]
                    dict[pk] = self.get(pk)
                else:
                    pk = iterKey.split(':')[len(iterKey.split(':'))-1]
                    dict[pk] = self.get(keyPrefix, pk)
            return dict
        except Exception as ex:
            pass

    def get_hash(self, value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def valueChanged(self, value):
        prevContentHash = value.get("content_hash")
        newValue = jsonHelper.preJsonSetToDynamoDb(obj=value, excludeProps=[ 'updated', 'content_hash' ])
        currentContentHash = self.get_hash(newValue)
        if not prevContentHash or prevContentHash != currentContentHash:
            return newValue, currentContentHash
        return newValue, None
    
    def exists(self, key):
        # Create tenant-aware key
        tenant_key = f"{self.countryCode}#{self.eventType}"
        result = self.client.exists(f'{self.env}:{tenant_key}:{key}')
        return result

    def rename(self, oldKey, newKey):
        # Create tenant-aware keys
        tenant_key = f"{self.countryCode}#{self.eventType}"
        self.client.rename(f'{self.env}:{tenant_key}:{oldKey}', f'{self.env}:{tenant_key}:{newKey}')

    def delete(self, key):
        # Create tenant-aware key
        tenant_key = f"{self.countryCode}#{self.eventType}"
        self.client.delete(f'{self.env}:{tenant_key}:{key}')

    def deleteByFilter(self, filter):
        iterKeys = self.client.scan_iter(filter)
        for iterKey in list(iterKeys):
            self.delete(iterKey)

    def truncate(self):
        pass

    def getFields(self, fieldName=None):
        if fieldName:
            value = self.get(f'fields:{fieldName}')
        else:
            value = self.getDict('fields')
        return value

    def setField(self, fieldName, value):
        key = f'fields:{fieldName}'
        self.set(key, value)

    def getRules(self, ruleName=None):
        if ruleName:            
            value = self.get(f'rules:{ruleName}')
        else:
            value = self.getDict('rules')
        return value

    def setRule(self, ruleName, value):
        key = f'rules:{ruleName}'
        self.set(key, value)

    def getSections(self, sectionName=None):
        if sectionName:
            value = self.get(f'sections:{sectionName}')
        else:
            value = self.getDict('sections')
        return value

    def setSection(self, sectionName, value):
        key = f'sections:{sectionName}'
        self.set(key, value)

    def getTournaments(self, tournamentName=None):
        if tournamentName:
            value = self.get(f'tournaments:{tournamentName}')
        else:
            value = self.getDict('tournaments')
        return value

    def setTournament(self, tournamentName, value):
        key = f'tournaments:{tournamentName}'
        self.set(key, value)

    def getLeagueTables(self, tournamentName, teamName=None):
        if teamName:
            value = self.get(f'tables:{tournamentName}:{teamName}')
        else:
            value = self.getDict(f'tables:{tournamentName}')
        return value

    def setLeagueTable(self, tournamentName, value):
        for teamName in value:
            teamValue = value[teamName]
            key = f'tables:{tournamentName}:{teamName}'
            self.set(key, teamValue)

    def getTournamentGames(self, tournamentName, gamePk=None):
        if gamePk:
            value = self.get(f'games:{tournamentName}:games:{gamePk}')
        else:
            value = self.getDict(f'games:{tournamentName}:games')
        return value or {}
    
    def setTournamentGame(self, tournamentName, gamePk, value):
        key = f'games:{tournamentName}:games:{gamePk}'
        if self.exists(key):
            newKey = f'games:{tournamentName}:history:{gamePk}:{jsonHelper.datetime_to_strfull(helpers.localNow())}'
            self.rename(key, newKey)
        self.set(key, value)

    def archiveTournamentGame(self, tournamentName, gamePk):
        oldKey = f'games:{tournamentName}:games:{gamePk}'
        newKey = f'games:{tournamentName}:archived:{gamePk}'
        self.rename(oldKey, newKey)

    def getTournamentGamesArchived(self, tournamentName, gamePk=None):
        if gamePk:
            value = self.get(f'games:{tournamentName}:archived:{gamePk}')
        else:
            value = self.getDict(f'games:{tournamentName}:archived')
        return value or {}

    def getRefereeProperties(self, refId=None, propertyName=None):
        key = 'referees'
        if refId:
            key += f':{refId}:props'
        else:
            key += ':*:props'
        if propertyName:
            key += f':{propertyName}'

        if refId and propertyName:
            value = self.get(f'referees:{refId}:props:{propertyName}')
        else:        
            value = self.getDict(key)
        return value or {}

    def setRefereeProperties(self, refId, value, propertyName):
        if propertyName:
            key = f'referees:{refId}:props:{propertyName}'
            self.set(key, value)
        else:
            key = f'referees:{refId}:props'
            self.setDict(key, value)

    def getRefereeGames(self, refId=None, gamePk=None):
        key = 'referees'
        if refId:
            key += f':{refId}:games'
        else:
            key += ':*:games'
        if gamePk:
            key += f':{gamePk}'

        if refId and gamePk:
            value = self.get(f'referees:{refId}:games:{gamePk}')
        else:        
            value = self.getDict(key)
        return value or {}

    def setRefereeGame(self, refId, gamePk, value):
        key = f'referees:{refId}:games:{gamePk}'
        if value.get('gameDetail'):
            del value['gameDetail']
        self.set(key, value)

    def removeRefereeGame(self, refId, gamePk):
        oldKey = f'referees:{refId}:games:{gamePk}'
        newKey = f'referees:{refId}:gamesRemoved:{gamePk}'
        self.rename(oldKey, newKey)

    def archiveRefereeGame(self, refId, gamePk):
        oldKey = f'referees:{refId}:games:{gamePk}'
        newKey = f'referees:{refId}:gamesArchived:{gamePk}'
        self.rename(oldKey, newKey)

    def getRefereeReviews(self, refId=None, gamePk=None):
        key = 'referees'
        if refId:
            key += f':{refId}:reviews'
        else:
            key += ':*:reviews'
        if gamePk:
            key += f':{gamePk}'

        if refId and gamePk:
            value = self.get(f'referees:{refId}:reviews:{gamePk}')
        else:        
            value = self.getDict(key)
        return value or {}

    def setRefereeReview(self, refId, gamePk, value):
        key = f'referees:{refId}:reviews:{gamePk}'
        self.set(key, value)

    def getRefereeTemplates(self, mobileNo=None):
        key = 'referees'
        if mobileNo:
            key += f':{mobileNo}:templates'
        else:
            key += ':*:templates'
        value = self.getDict(key)
        return value or {}

    def setRefereeTemplate(self, mobileNo, msgSid, value):
        key = f'referees:{mobileNo}:templates:{msgSid}'
        self.set(key, value)

    def getRefereeMessages(self, mobileNo=None, recentDays=None):
        key = 'referees'
        if mobileNo:
            key += f':{mobileNo}:messages'
        else:
            key += ':*:templates'
        value = self.getDict(key)
        return value or {}

    def setRefereeMessage(self, mobileNo, msgSid, value):
        key = f'referees:{mobileNo}:messages:{msgSid}'
        self.set(key, value)

    def archiveRefereeMessage(self, mobileNo, msgSid):
        oldKey = f'referees:{mobileNo}:messages:{msgSid}'
        newKey = f'referees:{mobileNo}:messagesArchived:{msgSid}'
        self.rename(oldKey, newKey)

    def getGameDetail(self, game):
        tournamentName = game.get('tournamentName')
        gamePk = game.get('pk')
        if not gamePk:
            return None
        gameDetail = self.getTournamentGames(tournamentName, gamePk) or self.get(f'games:{tournamentName}:archived:{gamePk}')
        return gameDetail

    def setGameDetail(self, tournamentName, gamePk, gameDetail):
        self.setTournamentGame(tournamentName, gamePk, gameDetail)

    def getMessage(self, msgSid):
        value = self.get('messages', msgSid)
        return value
    
    def setMessage(self, msgSid, value):
        self.set(f'messages:{msgSid}', value)

    def setInvocation(self, invocationId, value):
        self.set(f'lambdaInvocationsTracking:{invocationId}', value)

    def removeRefereeReview(self, refId, gamePk):
        value = self.getRefereeReviews(refId, gamePk)
        if value:
            #self.set('refereeGamesRemoved', value, refId, gamePk)
            self.delete('refereeReviews', refId, gamePk)

    def getGameDetailById(self, gameId:str):
        reference = self.getReferenceId('tournamentGames', gameId)
        if reference is None:
            return None
        tournamentName = reference.get('tournamentName')
        gamePk = reference.get('gamePk')
        if gamePk is None:
            return None
        gameDetail = self.getTournamentGames(tournamentName, gamePk)        
        return gameDetail

    def getRefGameActions(self, refId, gamePk, actionId=None):
        value = None
        if actionId:
            value = self.get('actions', f'{refId}_{gamePk}', actionId)
        else:
            value = self.getDict('actions', f'{refId}_{gamePk}')
        return value

    def setRefGameActions(self, refId, gamePk, actionId, value):
        return self.set('actions', value, f'{refId}_{gamePk}', actionId)

    def getGameActions(self, gamePk, actionId=None):
        value = None
        if actionId:
            value = self.get('actions', gamePk, actionId)
        else:
            value = self.getDict('actions', gamePk)
        return value

    def setGameActions(self, gamePk, actionId, value):
        return self.set('actions', value, gamePk, actionId)

    def getReferenceId(self, target:str, id:str=None):
        value = None
        if id:
            value = self.get('referenceIds', target, id)
        else:
            value = self.getDict('referenceIds', target)
        return value

    def setReferenceId(self, target:str, id:str, value):
        return self.set('referenceIds', value, target, id)
