from abc import ABC, abstractmethod
import json
import asyncio
import os
import sys
import json
import re
from datetime import datetime, timedelta
from typing import Any
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.db.enumTypes import EntityType

class DbClientBase(ABC):

    CacheTypes:dict[EntityType, dict[str, Any]] = {
        EntityType.CLIENTIDENTIFIERS: {'ttl': 1, 'partitionKeys': [], 'entityKeys': ['clientIdentifier']},   # 60 minutes
        EntityType.FIELDS: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['fieldName']},      # 1 day
        EntityType.TOURNAMENTS: {'ttl': 60*60, 'partitionKeys': [], 'entityKeys': ['tournamentName']},  # 1 hour
        EntityType.SEASONS: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['seasonName']},     # 1 hour
        EntityType.RULES: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['ruleName']},       # 1 hour
        EntityType.SECTIONS: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['sectionName']},    # 1 hour
        EntityType.ROLES: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['roleName']},       # 1 day
        EntityType.REFEREES: {'ttl': 60*60, 'partitionKeys': [], 'entityKeys': ['mobileNo/refereeId']},     # 1 hour
        EntityType.AREAS: {'ttl': 60*60, 'partitionKeys': [], 'entityKeys': ['areaName']},     # 1 hour
        EntityType.NOTIFICATIONTYPES: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['typeKey']},  # 1 day
        EntityType.DOCUMENTS: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['documentName']},   # 1 day
        EntityType.TENANTS: {'ttl': 24*60*60, 'partitionKeys': [], 'entityKeys': ['tenantName']}, # 1 day
        EntityType.REFEREEGAMES: {'ttl': 60*60, 'partitionKeys': ['refereeId'], 'entityKeys': ['gamePk'], 'excludeKeys': ['gameDetail']},   # 60 minutes
        EntityType.REFEREEREVIEWS: {'ttl': 60*60, 'partitionKeys': ['refereeId'], 'entityKeys': ['gamePk'], 'excludeKeys': ['reviewDetail']}, # 60 minutes
        EntityType.TOURNAMENTSGAMES: {'ttl': 60*60, 'partitionKeys': ['tournamentName'], 'entityKeys': ['gamePk']}, # 60 minutes
        EntityType.TOURNAMENTGAMESARCHIVED: {'ttl': 60*60, 'partitionKeys': ['tournamentName'], 'entityKeys': ['gamePk']}, # 60 minutes
        EntityType.REFEREETEMPLATES: {'ttl': 60*60, 'partitionKeys': ['refereeId'], 'entityKeys': ['action' ,'msgSid']}, # 60 minutes
        EntityType.REFEREEAVAILABILITY: {'ttl': 60*60, 'partitionKeys': ['refereeId'], 'entityKeys': []}, # 60 minutes
        EntityType.COLLECTEDITEMS: {'ttl': 24*60*60, 'partitionKeys': ['objType', 'refereeId'], 'entityKeys': []}, # 1 day
        # alwaysMultiRecord: (target, target_id, notificationType, target_to) does not uniquely
        # identify one row - multiple notifications can legitimately share that whole tuple,
        # differing only by status/id (e.g. one 'created' + one 'deleted'/'sent' row for the
        # same identity) - never let the decorator auto-unwrap this to a single flat dict.
        EntityType.NOTIFICATIONS: {'ttl': 60*60, 'partitionKeys': ['target', 'target_id'], 'entityKeys': ['notificationType', 'target_to'], 'alwaysMultiRecord': True}, # 60 minutes
        EntityType.KEYVAL: {'ttl': 60*60, 'partitionKeys': ['key'], 'entityKeys': []}, # 1 day
        EntityType.MESSAGES: {'ttl': 60*60, 'partitionKeys': ['msgSid'], 'entityKeys': []}, # 60 minutes
        EntityType.REFEREEMESSAGES: {'ttl': 5*60, 'partitionKeys': ['refereeId', 'direction'], 'entityKeys': ['msgSid']}, # 60 minutes
        EntityType.REFEREELOCATIONS: {'ttl': 7*24*60*60, 'partitionKeys': ['refereeId'], 'entityKeys': []}, # 7 days
        EntityType.POSITIONUPDATES: {'ttl': 7*24*60*60, 'partitionKeys': ['refereeId'], 'entityKeys': []}, # 7 days
        EntityType.INVOCATIONS: {'ttl': 7*24*60*60, 'partitionKeys': ['invocationId'], 'entityKeys': []}, # 7 days
        EntityType.REFERENCEIDS: {'ttl': 7*24*60*60, 'partitionKeys': ['target', 'target_id'], 'entityKeys': []}, # 7 days
        EntityType.POLLS: {'ttl': 7*24*60*60, 'partitionKeys': ['pollId'], 'entityKeys': []}, # 7 days
        EntityType.POLLVOTES: {'ttl': 7*24*60*60, 'partitionKeys': ['pollId', 'refereeId'], 'entityKeys': ['questionId']}, # 7 days
        EntityType.LEAGUETABLES: {'ttl': 7*24*60*60, 'partitionKeys': [], 'entityKeys': ['tournamentName']}, # 60 minutes
    }

    def __init__(self, env, logger:Logger):
        try:
            self.env = env
            self.logger = logger

            self.logger.info(f'DbClient starts...')
        except Exception as ex:
            self.logger.error('init', ex)

    def getTenantKey(self, tenantKey:str):
        """Create tenant-aware partition key"""
        return tenantKey

    @abstractmethod
    def get(self, keyPrefix, entityKey=None, jsonDumps=True):
        pass

    @abstractmethod
    def set(self, key, value, expiry=None, jsonDumps=True):
        pass

    @abstractmethod
    def valueChanged(self, value):
        pass
    
    def setMediaFileMetadata(self, file_id, metadata):
        """Store media file metadata"""
        key = f"media_file#{file_id}"
        return self.set(key, metadata)
    
    def getMediaFileMetadata(self, file_id):
        """Retrieve media file metadata"""
        key = f"media_file#{file_id}"
        return self.get(key)
    
    def getMediaFilesByMobile(self, mobile_no):
        """Get all media files for a specific mobile number"""
        key_prefix = "media_file#"
        all_media = self.get(key_prefix)
        if not all_media:
            return []
        
        # Filter by mobile number
        mobile_media = []
        for file_id, metadata in all_media.items():
            if isinstance(metadata, dict) and metadata.get('from_mobile') == mobile_no:
                mobile_media.append({
                    'file_id': file_id,
                    'metadata': metadata
                })
        
        return mobile_media
    
    def getMediaFilesByMessageSid(self, message_sid):
        """Get all media files for a specific message SID"""
        key_prefix = "media_file#"
        all_media = self.get(key_prefix)
        if not all_media:
            return []
        
        # Filter by message SID
        message_media = []
        for file_id, metadata in all_media.items():
            if isinstance(metadata, dict) and metadata.get('message_sid') == message_sid:
                message_media.append({
                    'file_id': file_id,
                    'metadata': metadata
                })
        
        return message_media

    @abstractmethod
    def getDict(self, keyPrefix, entityKey=None, jsonDumps=True, asIsEntityKey=False):
        pass

    @abstractmethod
    def setDict(self, keyPrefix, data):
        pass

    @abstractmethod
    def exists(self, key):
        pass

    @abstractmethod
    def rename(self, oldKey, newKey):
        pass

    @abstractmethod
    def delete(self, key):
        pass

    @abstractmethod
    def deleteByFilter(self, filters):
        pass

    @abstractmethod
    def truncate(self):
        pass

    def saveJsonFileInDb(self, keyPrefix, filePath):
        data = jsonHelper.load_from_file(filePath)
        if isinstance(data, dict):
            for entityKey in data:
                row = data[entityKey]
                self.set(f'{keyPrefix}:{entityKey}', row)

    def extractWildcardMatch(self, pattern, text):
        # Convert fnmatch-style wildcards to regex
        regex_pattern = re.escape(pattern).replace(r"\*", "(.*?)").replace(r"\?", "(.)")

        # Match regex pattern
        match = re.fullmatch(regex_pattern, text)
        
        if match:
            return match.groups()  # Return captured wildcard matches
        return None  # No match found

    async def loadAllData(self, directory):
        try:
            fileDictionaries = {
                'fields.json': 'fields',
                #'referees.json': 'referees',
                '*games/refId*_v8.json': 'referees:{x}:games',
                '*reviews/refId*_v8.json': 'referees:{x}:reviews',
                '*templates/refId*.json': 'referees:{x}:templates',
                '*/summary/refId*_collectGamesSummary.json': 'referees:{x}:collectGamesSummary',
                '*/summary/refId*_gamesEvents.json': 'referees:{x}:gamesEvents',
                'rules.json': 'rules',
                'sections.json': 'sections',
                'tournaments.json': 'tournaments',
                '*games/leagueId*.json': 'league:{x}:games',
                '*tables/leagueId*.json': 'league:{x}:table'
            }

            directory_path = Path(directory)  # Change this to your target directory

            # 🔹 Ensure the directory exists
            if not directory_path.exists() or not directory_path.is_dir():
                print("❌ Directory does not exist!")
            else:
                # 🔹 List all files in the directory
                for file in directory_path.iterdir():
                    if file.is_file():  # Only process files, ignore subdirectories
                        if file.suffix == '.json':
                            fullPath = str(file)
                            parentName = file.resolve().parent.name
                            fileName = file.name
                            if fileName in fileDictionaries:
                                keyPrefix = fileDictionaries[fileName]
                                self.saveJsonFileInDb(keyPrefix, fullPath)
                                self.logger.info(f"📂 Found file: {file}")
                            else:
                                for fileDictionary in fileDictionaries:
                                    matchedText = self.extractWildcardMatch(fileDictionary, fullPath)
                                    if matchedText:
                                        keyPrefix = fileDictionaries[fileDictionary]
                                        keyPrefix = keyPrefix.replace('{x}', matchedText[len(matchedText)-1])
                                        self.saveJsonFileInDb(keyPrefix, fullPath)
                                    self.logger.info(f"📂 Found file: {file}")
                    else:
                        await self.loadAllData(str(file))
        except Exception as ex:
            pass

    @abstractmethod
    def getFields(self, fieldName=None):
        pass

    @abstractmethod
    def setField(self, fieldName, value):
        pass

    @abstractmethod
    def getRoles(self, roleName=None):
        pass

    @abstractmethod
    def setRole(self, roleName, value):
        pass

    @abstractmethod
    def getRules(self, ruleName=None):
        pass

    @abstractmethod
    def setRule(self, ruleName, value):
        pass

    @abstractmethod
    def getSeasons(self, season=None):
        pass

    @abstractmethod
    def setSeason(self, season=None):
        pass

    @abstractmethod
    def getSections(self, sectionName=None):
        pass

    @abstractmethod
    def setSection(self, sectionName, value):
        pass

    @abstractmethod
    def getTournaments(self, tournamentName=None):
        pass

    @abstractmethod
    def setTournament(self, tournamentName, value):
        pass

    @abstractmethod
    def getLeagueTables(self, tournamentName):
        pass

    @abstractmethod
    def setLeagueTable(self, tournamentName, value):
        pass

    @abstractmethod
    def getTournamentGames(self, tournamentName, season=None, gamePk=None, gamePks=None, nonArchivedOnly=False):
        pass

    @abstractmethod
    def setTournamentGame(self, tournamentName, gamePk, value):
        pass

    @abstractmethod
    def deleteTournamentGame(self, tournamentName, gamePk):
        pass

    @abstractmethod
    def archiveTournamentGame(self, tournamentName, gamePk):
        pass

    @abstractmethod
    def getTournamentGamesArchived(self, tournamentName, gamePk=None):
        pass

    @abstractmethod
    def getRefereeProperties(self, mobileNo=None, refereeId=None, propertyName=None, **entityKeys):
        """Global (cross-tenant) referee profile from the referees table."""
        pass

    @abstractmethod
    def setRefereeProperties(self, mobileNo=None, refereeId=None, value=None, propertyName=None, **entityKeys):
        """Upsert a global referee profile into the referees table."""
        pass

    @abstractmethod
    def getTenantRefereeProperties(self, tenantKey: str = None, mobileNo=None, refereeId=None, propertyName=None, **entityKeys):
        """Tenant-scoped referee properties (status, role, etc.)."""
        pass

    @abstractmethod
    def setTenantRefereeProperties(self, tenantKey: str = None, mobileNo: str = None, refereeId=None, value=None, propertyName=None, **entityKeys):
        """Upsert tenant-scoped referee properties."""
        pass

    @abstractmethod
    def getRefereeAvailaiblity(self, mobileNo:str=None, refereeId=None, fromDate:datetime=None, toDate:datetime=None):
        pass

    @abstractmethod
    def setRefereeAvailaiblity(self, mobileNo:str=None, refereeId=None, value=None):
        pass

    @abstractmethod
    def getClientIdentifier(self, clientIdentifier):
        pass

    @abstractmethod
    def setClientIdentifier(self, clientIdentifier, pushSubscription=None, mobileNo=None, userAgent=None, platform=None):
        pass

    @abstractmethod
    def getRefereeGames(self, refId=None, mobileNo=None, refereeId=None, season=None, gamePk=None, includeArchived=False, includeRemoved=False, includeCanceled=False, fromDate=None, toDate=None):
        pass

    @abstractmethod
    def setRefereeGame(self, value, refId=None, mobileNo=None, refereeId=None, gamePk=None):
        pass

    @abstractmethod
    def removeRefereeGame(self, refId=None, mobileNo=None, refereeId=None, gamePk=None):
        pass

    @abstractmethod
    def archiveRefereeGame(self, refId=None, mobileNo=None, refereeId=None, gamePk=None):
        pass

    @abstractmethod
    def getRefereeReviews(self, refId=None, mobileNo=None, refereeId=None, season=None, gamePk=None, removed=False, fromDate=None, toDate=None):
        pass

    @abstractmethod
    def setRefereeReview(self, value, refId=None, mobileNo=None, refereeId=None, gamePk=None):
        pass

    @abstractmethod
    def removeRefereeReview(self, refId=None, mobileNo=None, refereeId=None, gamePk=None):
        pass

    @abstractmethod
    def getRefereeTemplates(self, mobileNo, status='created'):
        pass

    @abstractmethod
    def setRefereeTemplate(self, mobileNo, msgSid, value):
        pass

    @abstractmethod
    def getRefereeMessages(self, mobileNo, recentDays=None):
        pass

    @abstractmethod
    def setRefereeMessage(self, mobileNo, msgSid, value):
        pass

    @abstractmethod
    def getGameDetail(self, game:dict):
        pass

    @abstractmethod
    def getMessage(self, msgSid):
        pass

    @abstractmethod
    def setMessage(self, msgSid, value):
        pass

    @abstractmethod
    def setKeyVal(self, key, value):
        pass

    @abstractmethod
    def getKeyVal(self, key):
        pass
    
    @abstractmethod
    def getPositionUpdates(self, mobileNo):
        pass

    @abstractmethod
    def setPositionUpdate(self, mobileNo, value):
        pass

    @abstractmethod
    def getRefereeLocations(self, mobileNo, timestamp=None):
        pass

    @abstractmethod
    def setRefereeLocation(self, mobileNo, timestamp, value):
        pass

    @abstractmethod
    def setInvocation(self, invocationId, value):
        pass

    @abstractmethod
    def getReferenceId(self, target:str, target_id:str=None):
        pass

    @abstractmethod
    def setReferenceId(self, target:str, target_id:str, value):
        pass
    
    @abstractmethod
    def getNotifications(self, tenantKey:str, target:str, target_id:str=None, notificationType:str=None, to:str=None, timestamp:int=None, status:str=None, **entityKeys):
        pass

    @abstractmethod
    def setNotifications(self, tenantKey:str, target:str, target_id:str, notificationType:str, to:str, timestamp:int, value):
        pass

    @abstractmethod
    def getDocuments(self):
        pass

    @abstractmethod
    def getTenants(self):
        pass

    @abstractmethod
    def getPolls(self, pollId=None, **entityKeys):
        pass

    @abstractmethod
    def setPoll(self, pollId, value=None):
        pass

    @abstractmethod
    def getPollVotes(self, pollId, mobileNo=None, **entityKeys):
        pass
    
    @abstractmethod
    def setPollVote(self, pollId, mobileNo, questionId, value=None):
        pass

    @abstractmethod
    def incrementRateLimit(self, action: str, window: str, limit: int, ttl_seconds: int) -> bool:
        """Atomically increment the counter for (action, window).
        Returns True if under limit (request allowed), False if blocked."""
        pass