import logging
from datetime import datetime, timedelta, timezone
import os
import sys
from pathlib import Path
import asyncio
import uuid
#from dependency_injector import containers, providers
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.commonHelper import CommonHelper
from shared.logger import Logger
from shared.handleUsers import HandleUsers
from shared.messaging import MessagingService
from shared.db import CacheService

class HandleRefereeData():
    def __init__(self, logger:Logger, cacheService:CacheService, commonHelper:CommonHelper, messagingService:MessagingService, handleUsers:HandleUsers, referees_data:tuple):
        # Configure logging
        self.logger = logger
        self.cacheService = cacheService
        self.commonHelper = commonHelper
        self.messagingService = messagingService
        self.handleUsers = handleUsers
        (self.globalRefereesByMobile, self.refereesByRefId, self.refereesByMobile, self.refereesByGuid, self.globalRefereesByName) = referees_data

        self.fileVersion = os.getenv('fileVersion') or 'v'

        self.hebrew_days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        self.season = os.getenv('season')
        self.dataDic = {
            'pk' : 'pk',
            'objText': 'objText',
            'games' : {
                'title': 'שיבוצים',
                'generate': self.commonHelper.generateGameDetails
            },
            'reviews': {
                'title': 'ביקורות',
                'generate': self.commonHelper.generateReviewDetails,
            }
        }

        self.refIdsPartition = self.resolveRefIdsPartition()
        self.openWindowReminder = int(os.getenv('openWindowReminder') or '18')
        self.openWindowLastReminder = int(os.getenv('openWindowLastReminder') or '22')
        self.activeRefereeByRefId = {}
        self.activeRefereeByMobileNos = {}

    def resolveRefIdsPartition(self) -> list:
        app_replicas_raw = os.getenv('APP_REPLICAS') or '1'
        replica_slot_raw = os.getenv('REPLICA_SLOT') or '1'
        try:
            app_replicas = int(app_replicas_raw)
            replica_slot = int(replica_slot_raw)

            if app_replicas <= 0:
                raise ValueError(f'APP_REPLICAS must be > 0, got {app_replicas}')
            if replica_slot < 1 or replica_slot > app_replicas:
                raise ValueError(f'REPLICA_SLOT must be in range [1, {app_replicas}], got {replica_slot}')

            partition = [str(digit) for digit in range(10) if digit % app_replicas == replica_slot - 1]
            self.logger.debug(f'resolveRefIdsPartition from replicas APP_REPLICAS: {app_replicas} REPLICA_SLOT: {replica_slot} refIdsPartition: {partition}')
            return partition

        except (TypeError, ValueError) as ex:
            fallback_partition = [part.strip() for part in (os.getenv('refIdsPartition') or '0,1,2,3,4,5,6,7,8,9').split(',') if part.strip()]
            self.logger.warning(f'resolveRefIdsPartition invalid APP_REPLICAS/REPLICA_SLOT values APP_REPLICAS: {app_replicas_raw} REPLICA_SLOT: {replica_slot_raw}. Falling back to refIdsPartition. Error: {ex}')
            self.logger.info(f'resolveRefIdsPartition from fallback refIdsPartition: {fallback_partition}')
            return fallback_partition

    def getRefereeGames(self, tenantKey, mobileNo, **filters) -> dict:
        games = {}
        for tenantKey in tenantKey if isinstance(tenantKey, list) else [tenantKey]:
            refereeDetail = self.refereesByMobile.get(tenantKey, {}).get(mobileNo)
            if refereeDetail:
                if refereeDetail.get('refId'):
                    games = games | self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=refereeDetail['refId'], **filters)
                else:
                    games = games | self.cacheService.getRefereeGamesNew(tenantKey=tenantKey, mobileNo=mobileNo, **filters)
        
        return games

    def getRefereeReviews(self, tenantKey, mobileNo, **filters) -> dict:
        reviews = {}
        for tenantKey in tenantKey if isinstance(tenantKey, list) else [tenantKey]:
            refereeDetail = self.refereesByMobile.get(tenantKey, {}).get(mobileNo)
            if refereeDetail.get('refId'):
                reviews = reviews | self.cacheService.getRefereeReviews(tenantKey=tenantKey, refId=refereeDetail['refId'], **filters)
            else:
                reviews = reviews | self.cacheService.getRefereeReviewsNew(tenantKey=tenantKey, mobileNo=mobileNo, **filters)
        
        return reviews

    def enrichRefereeItems(self, refereeItems):
        if refereeItems and 'gamePk' in refereeItems:
            items = [refereeItems]
        else:
            items = refereeItems.values()
        
        for item in items:
            gameDetail = self.cacheService.getGameDetail(tenantKey=item['tenantKey'], game=item)
            item['gameDetail'] = gameDetail
        
    async def getRefereeData(self, tenantKey, objType, refereeData):
        if objType not in refereeData or 'prevList' not in refereeData[objType] or not refereeData[objType]['prevList']:
            
            try:
                if objType not in refereeData:
                    refereeData[objType] = {}

                if objType == 'games':
                    refereeGames = self.getRefereeGames(tenantKey=tenantKey, mobileNo=refereeData['mobileNo'], includeArchived=True, includeRemoved=True, from_date=refereeData[objType]['fromDate'], to_date=refereeData[objType]['toDate'], forceReload=True)
                    refereeData[objType]['prevList'] = refereeGames
                else:
                    refereeData[objType]['prevList'] = self.getRefereeReviews(tenantKey=tenantKey, mobileNo=refereeData['mobileNo'], from_date=refereeData[objType]['fromDate'], to_date=refereeData[objType]['toDate'], forceReload=True)
                
                refereeData[objType]['fileDateTime'] = self.cacheService.getRefereeProperty(tenantKey=tenantKey, mobileNo=refereeData['mobileNo'], propertyName=f'fileDateTime_{objType}')
            except Exception as ex:
                self.logger.error(f'getRefereeData', ex)
        
    async def getDataByMobileNo(self, mobileNo, objType, shortResponse=False):
        try:
            self.logger.info(f'getDataByMobileNo mobileNo: {mobileNo} objType: {objType} shortResponse: {shortResponse}')
            
            globalRefereeDetail = self.globalRefereesByMobile[mobileNo]
            items = None
            now = helpers.localNow()
            if objType == 'games':
                items = self.getRefereeGames(tenantKey=globalRefereeDetail['activeTenantKeys'], mobileNo=mobileNo, from_date=now)
            else:
                items = self.getRefereeReviews(tenantKey=globalRefereeDetail['activeTenantKeys'], mobileNo=mobileNo)
            data = f"רשימת {self.dataDic[objType]['title']}:"
            if len(items) == 0:
                data = f'{data}\nריקה'
            sortedItems = sorted(list(items.values()), key=lambda item: item.get('date'))
            for item in sortedItems:
                self.logger.debug(f'pk={item.get("gamePk")}')
                gameDetail = {}
                includeReferees = True
                includeReviewer = False
                if objType == 'games':
                    gameDetail = self.cacheService.getGameDetail(tenantKey=item.get('tenantKey'), game=item)
                    if shortResponse == False:
                        tournament = self.cacheService.get_tournament_by_name(tenantKey=item.get('tenantKey'), tournamentName=gameDetail['tournamentName'])
                        if tournament:
                            rule = self.cacheService.get_rule_by_name(tenantKey=item.get('tenantKey'), ruleName=tournament['rules'])
                            if rule.get('includeReviewer', False) == True:
                                includeReviewer = True
                    else:
                        includeReferees = False
                itemDesc = self.dataDic[objType]['generate'](tenantKey=item.get('tenantKey'), gameDetail=item | gameDetail, includeReferees=includeReferees, includeReviewer=includeReviewer)
                if data:
                    data += '\n\n'
                data += itemDesc

            return data
        except Exception as ex:
            self.logger.error('getDataByMobileNo', ex)
            return 'ארעה שגיאה'

    async def handleWindowOpenReminder(self, refereeDetail, message=None):
        if self.openWindowReminder < 0:
            return True

        prevLastMessageTime = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', mobileNo=refereeDetail['mobileNo'], propertyName='lastMessageTime')
        prevLastReminderTime = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', mobileNo=refereeDetail['mobileNo'], propertyName='lastReminderTime')
        (windowIsOpen, lastMessageTime, timeElapsed) = self.messagingService.checkIf24HoursWindowIsOpen(mobileNo=refereeDetail['mobileNo'])
        if windowIsOpen == False:
            self.logger.warning(f'24 hours window is closed, last message time {timeElapsed}', refereeDetail=refereeDetail)
        now = helpers.localNow()
        openWindowMessage = message
        if (timeElapsed == None or timeElapsed.total_seconds() > 60 * 60 * self.openWindowReminder) \
                    and (prevLastMessageTime != lastMessageTime or prevLastReminderTime == None \
                         or False and (now - prevLastReminderTime).total_seconds() > 60 * 60 * 24) \
                or (windowIsOpen == False and message):
            await self.messagingService.sendIceBreaker(refereeDetail=refereeDetail, message=openWindowMessage)
            lastMessageTime = lastMessageTime
            lastReminderTime = now
        elif False and (timeElapsed == None or timeElapsed.total_seconds() > 60 * 60 * self.openWindowLastReminder):
            prevLastMessageTime = refereeRecord.get('lastMessageTime2')
            if prevLastMessageTime != lastMessageTime:
                await self.messagingService.sendIceBreaker(refereeDetail=refereeDetail, message=openWindowMessage)
                lastMessageTime2 = lastMessageTime
                lastReminderTime2 = now

        self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=refereeDetail['mobileNo'], value=lastMessageTime, propertyName='lastMessageTime')
        self.cacheService.setRefereeProperty(tenantKey='GLOBAL', mobileNo=refereeDetail['mobileNo'], value=lastReminderTime, propertyName='lastReminderTime')
        
        return windowIsOpen

    def loadActiveRefereeDetails(self, filePath=None, path=None, initial=False):
        try:
            self.activeRefereeByRefId = {}
            self.activeRefereeByMobileNos = {}
            activeTenantKeys = [ tenantKey for tenantKey, tenant in self.cacheService.getTenants().items() if tenant.get('active') == True ]
            self.activeRefereesByMobile = {}
            for tenantKey in activeTenantKeys:
                tenant = self.cacheService.getTenants().get(tenantKey)
                tenantActiveStatus = tenant.get('activeStatus')
                activeTenantRefereeDetails = { refereeDetail['refId']: refereeDetail for refereeDetail in self.refereesByMobile.get(tenantKey, {}).values() if refereeDetail.get('refId') and (tenantActiveStatus == 'all' or refereeDetail.get('status') == tenantActiveStatus) and (str(refereeDetail['refId'])[-1:] in self.refIdsPartition or str(refereeDetail['refId'])[-2:] in self.refIdsPartition)}
                activeTenantMobileNos = { mobileNo: refereeDetail for mobileNo, refereeDetail in self.refereesByMobile.get(tenantKey, {}).items() if refereeDetail.get('refId') and (tenantActiveStatus == 'all' or refereeDetail.get('status') == tenantActiveStatus) and (str(refereeDetail['refId'])[-1:] in self.refIdsPartition or str(refereeDetail['refId'])[-2:] in self.refIdsPartition) }
                self.activeRefereesByMobile = { **activeTenantMobileNos, **self.activeRefereesByMobile }
                self.activeRefereeByRefId[tenantKey] = activeTenantRefereeDetails
                self.activeRefereeByMobileNos[tenantKey] = activeTenantMobileNos
                self.logger.info(f'Active Referees#: {len(activeTenantRefereeDetails)} tenantKey: {tenantKey} refIdsPartition: {self.refIdsPartition}')
        except Exception as ex:
            self.logger.error('loadActiveRefereeDetails', ex)
            
    def dayOfWeekInHebrew(self, date):
        if not date:
            return ''
        dow_hebrew = self.hebrew_days[date.weekday()] 
        return dow_hebrew      

    def daySeqInHebrew(self, dateSeq):
        today_dow = helpers.localNow().weekday()
        game_dow = (dateSeq + today_dow if dateSeq + today_dow < 7 else (dateSeq + today_dow) % 7)
        dow_hebrew = self.hebrew_days[game_dow] 
        return dow_hebrew      

    def getCollectionSummaryFile(self, tenantKey, refId=None):
        summaryFile = f'{os.getenv("MY_DATA_FOLDER", "/run/data/")}summary/{"tenantKey" + tenantKey + "_" if tenantKey else ""}{"refId" + refId +"_" if refId else ""}collectGamesSummary.json'
        return summaryFile
    
    async def collectGamesSummary(self, tenantKey, refId=None):        
        self.logger.info(f'generating games summary file{" refId=" + refId if refId else ""}...')
        barData = {}
        games = []
        referees = []
        gamesReferees = []

        l = []
        allSections = []
        allDays = []

        if refId:
            refereeDetail = self.refereesByRefId.get(tenantKey, {}).get(refId)
            refereesDetails = { refId: refereeDetail}
        else:
            refereesDetails = self.handleUsers.refereesByRefId

        for refPk in refereesDetails:
            refereeDetail = refereesDetails[refPk]
            refereeData = { 'refId': refPk}
            await self.getRefereeData(tenantKey=tenantKey, objType='games', refereeData=refereeData)
            if refereeData and refereeData.get('games'):
                for gamePk in refereeData['games']['currentList']:
                    if gamePk not in games:
                        games.append(gamePk)
        
                    if refPk not in referees:
                        referees.append(refPk)

                    gamesReferees.append(f'{gamePk}-{refPk}')

                    game = refereeData['games']['currentList'][gamePk]
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=game)
                    tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=gameDetail['tournamentName'])
                    if tournament:
                        section = tournament['section']
                        if section:
                            leagueCup = 'ליגה' if tournament['tournament'] == 'league' else 'גביע'
                            if leagueCup == 'גביע':
                                l.append(f"{refereeDetail['name']}-{gamePk}")
                            section1 = f'{section}-{leagueCup}'
                        else:
                            section1 = tournament['text']
                    else:
                        section1 = 'ידידות'
                        leagueCup = ''

                    dateSeq = (gameDetail['date'].date() - helpers.localNow().date()).days
                    gameDay = f'{self.dayOfWeekInHebrew(game["date"])}{f"+{int(dateSeq/7)}" if dateSeq >=7 else ""}'

                    label = f'{section1}/{gameDay}'

                    if not section1 in allSections:
                        allSections.append(section1)
                    if not dateSeq in allDays:
                        allDays.append(dateSeq)
        
                    if not barData.get(label):
                        barData[label] = { 'section': section1, 'dateSeq': dateSeq, 'gameDay': gameDay, 'count': 0, 'sort': f'{dateSeq}/{section1}' }
                    barData[label]['count'] = barData[label]['count'] + 1

        barLabels = []
        barValues = []

        multiBarsByDay = []
        multiBarLabelsByDay = []
        multiBarValuesByDay = []

        multiBarsBySection = []
        multiBarLabelsBySection = []
        multiBarValuesBySection = []

        allBars = []

        prevByDay = None
        prevBySection = None

        sortedData = sorted(barData, key=lambda x: barData[x]['sort'])
        for label in sortedData:
            item = barData[label]
            barLabels.append(label)
            barValues.append(item['count'])

            allBars.append( {'label': label, 'section': item['section'], 'dateSeq': item['dateSeq'], 'gameDay': item['gameDay'], 'count': item['count'] })
            if prevByDay and item['gameDay'] != prevByDay:
                multiBarsByDay.append( { 'name': prevByDay, 'labels': multiBarLabelsByDay, 'values': multiBarValuesByDay } ) 
                multiBarLabelsByDay = []
                multiBarValuesByDay = []

            prevByDay = item['gameDay']

            multiBarLabelsByDay.append(item['section'])
            multiBarValuesByDay.append(item['count'])

        multiBarsByDay.append( { 'name': prevByDay, 'labels': multiBarLabelsByDay, 'values': multiBarValuesByDay } ) 

        sortedData = sorted(barData, key=lambda x: barData[x]['section'])
        for label in sortedData:
            item = barData[label]

            if prevBySection and item['section'] != prevBySection:
                multiBarsBySection.append( { 'name': prevBySection, 'labels': multiBarLabelsBySection, 'values': multiBarValuesBySection } ) 
                multiBarLabelsBySection = []
                multiBarValuesBySection = []

            prevBySection = item['section']

            multiBarLabelsBySection.append(item['dateSeq'])
            multiBarValuesBySection.append(item['count'])

        multiBarsBySection.append( { 'name': prevBySection, 'labels': multiBarLabelsBySection, 'values': multiBarValuesBySection } ) 

        allSections = sorted(allSections)
        allDays = sorted(allDays)
        allDaysInHebrew = [ f'{self.daySeqInHebrew(dateSeq)}{f"+{int(dateSeq/7)}" if dateSeq >=7 else ""}' for dateSeq in allDays ]
        alignedMultiBarsByDay = []
        for bar in multiBarsByDay:
            dictBar = dict(zip(bar['labels'], bar['values']))
            alignedValues = [dictBar.get(label, 0) for label in allSections]
            alignedBar = { 'name': bar['name'], 'labels': allSections, 'values': alignedValues }
            alignedMultiBarsByDay.append(alignedBar)

        alignedMultiBarsBySection = []
        multiBarsBySection =  sorted(multiBarsBySection, key=lambda bar: bar['name'])
        for bar in multiBarsBySection:
            dictBar = dict(zip(bar['labels'], bar['values']))
            alignedValues = [dictBar.get(label, 0) for label in allDays]
            alignedBar = { 'name': bar['name'], 'labels': allDaysInHebrew, 'values': alignedValues }
            alignedMultiBarsBySection.append(alignedBar)

        allBars =  sorted(allBars, key=lambda bar: bar['label'])

        dataFinal = { 'labels': barLabels, 'values': barValues, 'gamesCount': len(games), 'activeRefereesCount': len(referees), 'totalRefereesCount': len(refereesDetails), \
                     'gamesRefereesCount': len(gamesReferees), 'multiBarsByDay': alignedMultiBarsByDay, 'multiBarsBySection': alignedMultiBarsBySection, \
                    'allBars': allBars, 'lastUpdated': helpers.localNow().strftime('%Y-%m-%d %H:%M:%S') }
        summaryFile = self.getCollectionSummaryFile(tenantKey=tenantKey, refId=refId)
        jsonHelper.save_to_file(dataFinal, summaryFile)
        return summaryFile

    def getGamesEventsFile(self, tenantKey, refId=None):
        summaryFile = f'{os.getenv("MY_DATA_FOLDER", "/run/data/")}summary/{"tenantKey" + tenantKey + "_" if tenantKey else ""}{"refId" + refId +"_" if refId else ""}gamesEvents.json'
        return summaryFile
    
    async def getGamesEvents(self, tenantKey, refId=None):        
        self.logger.info(f'generating games events file{" refId=" + refId if refId else ""}...')
        gamesEvents = []

        if refId:
            refereeDetail = self.refereesByRefId.get(tenantKey, {}).get(refId)
            refereesDetails = { refId: refereeDetail}
        else:
            refereesDetails = self.handleUsers.refereesByRefId

        for refPk in refereesDetails:
            if not refId:
                gamesEvents = []
            refereeDetail = refereesDetails[refPk]
            refereeData = { 'refId': refPk}
            await self.getRefereeData(tenantKey=tenantKey, objType='games', refereeData=refereeData)
            if refereeData and refereeData.get('games'):
                for gamePk in refereeData['games']['currentList']:
                    game = refereeData['games']['currentList'][gamePk]
                    gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=game)
                    gameId = gameDetail['id'] if gameDetail else str(uuid.uuid4())
                    gamesEvents.append(
                        {
                            'id': gameId,
                            'title': f'{gameDetail.get("tournamentName")} - {gameDetail["gameTitle"]}',
                            'start': gameDetail['date'].isoformat(),
                            'end': (gameDetail['date'] + timedelta(hours=2)).isoformat(),
                            'extendedProps': {
                                'location': gameDetail['field'] if gameDetail.get('field') else '',
                                'description': ''
                            }
                        })

        gamesEventsFile = self.getGamesEventsFile(tenantKey=tenantKey, refId=refId)
        jsonHelper.save_to_file(gamesEvents, gamesEventsFile)

    def findRefereeRole(self, tenantKey, refereeDetail, gameReferees):
        if not gameReferees:
            return None
        
        gameReferees = { gameReferees[refereePk]['* name'] : refereePk for refereePk in gameReferees.keys() }
        bestMatchName = next(iter(gameReferees))
        if len(gameReferees) > 1:
            bestMatch = helpers.find_intuitive_matches(name=refereeDetail['name'], gameReferees=gameReferees, cutoff=0.6)
            if bestMatch == None:
                self.logger.error(f'findRefereeRole: {refereeDetail["name"]} not found in {gameReferees}')
                return None
            else:
                bestMatchName = bestMatch[0]
        self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=refereeDetail['mobileNo'], propertyName='refereeRefereeName', value=bestMatchName)
        bestMatchRole = gameReferees[bestMatchName]
        return bestMatchRole

    def findMostRelevantGameField(self, tenantKeys, mobileNo, latitude, longitude, retry:int):
        now = helpers.localNow()
        refereeGames = self.getRefereeGames(tenantKey=tenantKeys, mobileNo=mobileNo, includeArchived=True, from_date=now - timedelta(days=7), to_date=now + timedelta(days=2))
        sortedGames = sorted(refereeGames.values(), key=lambda refereeGame: refereeGame.get('date'), reverse=True)
        results = []
        minDistance = None
        mostRelevantField = None
        mostRelevantGame = None
        for game in sortedGames:
            gameDetail = self.cacheService.getGameDetail(tenantKey=game['tenantKey'], game=game)
            field = self.cacheService.get_field_by_name(tenantKey=game['tenantKey'], fieldName=gameDetail['field'])
            if field and field.get('addressDetails') and field.get('addressDetails').get('coordinates'):
                coordinates = field.get('addressDetails').get('coordinates')
                if coordinates.get('lat') and coordinates.get('lng'):
                    distance = helpers.calculate_distance_between_coordinates(lat1=coordinates.get('lat'), lng1=coordinates.get('lng'), lat2=latitude, lng2=longitude, unit='km')
                    results.append({ 'gamePk': game['gamePk'], 'distance': distance, 'field': field, 'game': game })

        sortedResults = sorted(results, key=lambda result: result['distance'])
        if sortedResults:
            if retry + 1 > len(sortedResults):
                return None, None, None
            mostRelevantField = sortedResults[retry]['field']
            mostRelevantGame = sortedResults[retry]['game']
        return mostRelevantField, mostRelevantGame, retry + 1 < len(sortedResults)

    def findMostRelevantGames(self, tenantKeys, mobileNo, start:int=0, limit:int=1):
        endOfDay = helpers.localNow().replace(hour=23, minute=59, second=59, microsecond=0).replace(tzinfo=None)
        refereeGames = self.getRefereeGames(tenantKey=tenantKeys, mobileNo=mobileNo, includeArchived=True, from_date=endOfDay - timedelta(days=14), to_date=endOfDay)
        sortedGames = sorted(refereeGames.values(), key=lambda refereeGame: refereeGame.get('date'), reverse=True)
        games = []
        for game in sortedGames[start:start+limit]:
            gameDetail = self.cacheService.getGameDetail(tenantKey=game['tenantKey'], game=game)
            if gameDetail:
                if not gameDetail.get('id'):
                    gameDetail['id'] = str(uuid.uuid4())[:8]
                    res = self.cacheService.setTournamentGame(tenantKey=game['tenantKey'], tournamentName=gameDetail['tournamentName'], gamePk=gameDetail['gamePk'], value=gameDetail)
                    gameDetail = res[0]
                games.append({ 'gameId': gameDetail['id'], 'gamePk': gameDetail['gamePk'], 'gameDetail': gameDetail })

        return games

    async def scanAllRefereesData(self):
        refereesDetails = self.handleUsers.refereesByRefId

        games = {}

        try:
            for tenantKey, referees in refereesDetails.items():
                for refPk, refereeDetail in referees.items():
                    updated = False
                    refereeData = { 'refId': refPk}
                    await self.getRefereeData(tenantKey=tenantKey, objType='games', season=self.season, refereeData=refereeData)
                    if refereeData and refereeData.get('games'):
                        for gamePk in refereeData['games']['currentList']:
                            if gamePk in games:
                                continue

                            game = refereeData['games']['currentList'][gamePk]
                            gameDetail = self.cacheService.getGameDetail(tenantKey=tenantKey, game=game)
                            refereesMobileNos = [ refDetail['* phone'] for refDetail in gameDetail['referees'] ]

                            refereeRole = self.findRefereeRole(tenantKey=tenantKey, refereeDetail=refereeDetail, gameReferees=gameDetail.get('referees'))
                            if refereeRole in [ 'mainReferee', 'mainReferee*', 'mainReferee1', 'mainReferee1*', 'mainReferee2', 'mainReferee3' ]:
                                games[gamePk] = refPk

                        if updated:
                            refereeData['games']['prevList'] = {}
                            self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=refereeData['refId'], gamePk=gamePk, value=game)

        except Exception as ex:
            pass

    async def createRefereeXGroups(self):
        refereesDetails = self.handleUsers.refereesByRefId
        chatGroupId = '120363420567954020@g.us'
        groupData = await self.messagingService.greenApiClient.handleAction('getGroupData', {'chatGroupId': chatGroupId})
        validReferees = {}
        invalidReferees = {}
        groupMembers = [ participant['id'] for participant in groupData['participants'] ]

        #chatGroupId = self.messagingService.greenApiClient.createGroup(groupName='RefereeX', tos=['0547799979'])
        for refId, referee in refereesDetails.items():
            if referee['status'] != 'pilot' and referee['status'] != 'suspended':
                continue
            refData = {'name':referee['name'], 'mobileNo':referee['mobileNo'], 'status':referee['status']}
            chatId = self.messagingService.greenApiClient.getChatId(referee['mobileNo'])
            if chatId in groupMembers:
                validReferees[refId] = refData
                continue
            response = await self.messagingService.greenApiClient.handleAction('addGroupParticipant', {'chatGroupId': chatGroupId, 'to': chatId})
            if response.get('addParticipant') == True:
                self.logger.info(f'refId={refId} response={response}', refereeDetail=referee)
                validReferees[refId] = refData
            else:
                self.logger.warning(f'refId={refId} response={response}', refereeDetail=referee)
                invalidReferees[refId] = refData
            pass

        self.logger.info(f'chatGroupId={chatGroupId}')
        jsonHelper.save_to_file(validReferees, './data/validReferees.json')
        jsonHelper.save_to_file(invalidReferees, './data/invalidReferees.json')
        pass

    async def getRefereeDataByMonth(self, tenantKey, mobileNo, fromDate):
        gamesData = []
        toDate = fromDate + timedelta(days=31)
        toDate = toDate.replace(day=1, hour=23, minute=59, second=59, microsecond=999999)
        toDate = toDate + timedelta(days=-1)
        refereeGames = self.getRefereeGames(tenantKey=[tenantKey], mobileNo=mobileNo, includeArchived=True, from_date=fromDate, to_date=toDate)
        for refereeGame in refereeGames.values():
            approveTime = refereeGame.get('approvedDate') - refereeGame.get('created') if refereeGame.get('approvedDate') else None
            declineTime = refereeGame.get('declinedDate') - refereeGame.get('created') if refereeGame.get('declinedDate') else None

            gameData = { 'gamePk': refereeGame.get('gamePk'), 'mobileNo': mobileNo, 'approveTime': approveTime, 'declineTime': declineTime }
            gamesData.append(gameData)
        
        return gamesData

    async def collectRefereesData(self):
        tenantKey = 'IL#handball#2025-26'
        allReferees = self.cacheService.getRefereesNoCache()
        tenantReferees = allReferees[tenantKey]

        refereeGamesData = {}

        now = helpers.localNow()
        fromDate = now - timedelta(days=31*4)

        while True:
            fromDate = fromDate.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            idx = f'{fromDate.year}-{fromDate.month}'
            refereeGamesData[idx] = {}
            for mobileNo in tenantReferees.keys():            
                refereeGamesPerMonth = await self.getRefereeDataByMonth(tenantKey=tenantKey, mobileNo=mobileNo, fromDate=fromDate)
                refereeGamesData[idx][mobileNo] = refereeGamesPerMonth
                self.logger.info(f'{idx} {mobileNo} {len(refereeGamesPerMonth)}')
            
            fromDate = fromDate + timedelta(days=31)
            if fromDate > now:
                break
        
        jsonHelper.save_to_file(refereeGamesData, './data/refereeGamesData.json')

    async def convertRefereeGamesReviewsToMobileNo(self):
        tenantKeys = self.cacheService.getTenants().keys()
        for tenantKey in tenantKeys:
            referees = self.refereesByMobile.get(tenantKey, {})
            for mobileNo, referee in referees.items():
                refereeGames = self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=referee['refId'], forceReload=True, includeArchived=True, includeRemoved=True, includeCanceled=True)
                for refereeGame in refereeGames.values():
                    if refereeGame.get('refId'):
                        del refereeGame['refId']
                    self.cacheService.setRefereeGameNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=refereeGame['gamePk'], value=refereeGame)
                refereeReviews = self.cacheService.getRefereeReviews(tenantKey=tenantKey, refId=referee['refId'], forceReload=True)
                for refereeReview in refereeReviews.values():
                    if refereeReview.get('refId'):
                        del refereeReview['refId']
                    self.cacheService.setRefereeReviewNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=refereeReview['gamePk'], value=refereeReview)

    async def updateRefereesPortalAllow(self):
        tenantKeys = self.cacheService.getTenants().keys()
        for tenantKey in tenantKeys:
            referees = self.refereesByMobile[tenantKey]
            for mobileNo, referee in referees.items():
                if not referee.get('status'):
                    self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value='inactive', propertyName='status')
                if referee.get('status') != 'active':
                    portalAllow = False
                else:
                    portalAllow = True
                self.cacheService.setRefereeProperty(tenantKey=tenantKey, mobileNo=mobileNo, value=portalAllow, propertyName='portalAllow')

    async def fixDuplicateTournamentGames(self, tenantKey):
        tournaments = self.cacheService.getTournaments(tenantKey=tenantKey, forceReload=True)
        for tournamentName, tournament in tournaments.items():
            for _tournamentName, _tournament in tournaments.items():
                if tournamentName == _tournamentName:
                    continue
                if tournamentName.endswith(_tournamentName):
                    continue
                if _tournamentName.endswith(tournamentName):
                    continue
                continue

    async def fixRefereeGamesTournamentName(self, tenantKey):
        tournaments = self.cacheService.getTournaments(tenantKey=tenantKey, forceReload=True)
        referees = self.refereesByMobile.get(tenantKey, {})
        for mobileNo, referee in referees.items():
            if False and mobileNo != 'tmpRefId:283594':
                continue
            if referee.get('refId'):
                refereeGames = self.cacheService.getRefereeGames(tenantKey=tenantKey, refId=referee['refId'], forceReload=True, includeArchived=True, includeRemoved=True, includeCanceled=True)
            else:
                refereeGames = self.cacheService.getRefereeGamesNew(tenantKey=tenantKey, mobileNo=mobileNo, forceReload=True, includeArchived=True, includeRemoved=True, includeCanceled=True)
            for refereeGame in refereeGames.values():
                if refereeGame.get('tournamentName'):
                    continue
                toUpdate = False
                if mobileNo in refereeGame:
                    del refereeGame[mobileNo]
                    toUpdate = True
                suitableTn = None
                for tn in tournaments.keys():
                    if refereeGame['gamePk'].startswith(tn):
                        if suitableTn is None or len(tn) > len(suitableTn):
                            suitableTn = tn
                if suitableTn:
                    refereeGame['tournamentName'] = suitableTn
                    toUpdate = True
                if not toUpdate:
                    continue
                if referee.get('refId'):
                    self.cacheService.setRefereeGame(tenantKey=tenantKey, refId=referee['refId'], gamePk=refereeGame['gamePk'], value=refereeGame)
                else:
                    self.cacheService.setRefereeGameNew(tenantKey=tenantKey, mobileNo=mobileNo, gamePk=refereeGame['gamePk'], value=refereeGame)

if __name__ == '__main__':
    from shared.appContainer import AppContainer
    import shared.configurationDI as configDI
    container = AppContainer()
    container.config.from_dict(configDI.configDI)
    container.init_resources()    

    #service = MessagingService(logger=logging.getLogger(), cacheService=cacheService, refereesByMobile={'+972547799979': {'name': 'Guy', 'mobileNo': '+972547799979'}}, activeClient='meta', metaClient=MetaClient(logger=logging.getLogger(), cacheService=cacheService, fromMobile='+972547799979', useClient=True, apiVersion='v24.0', fromPhoneNumberId='120702945000013', whatsappBusinessAccountId='120702945000013'))
    handleRefereeData = container.handle_referee_data()
    asyncio.run(handleRefereeData.fixDuplicateTournamentGames(tenantKey='IL#football#2025-26'))
    #games = handleRefereeData.findMostRelevantGames(tenantKeys=['IL#football#2025-26'], mobileNo='+972547799979', start=0, limit=10)
    #asyncio.run(handleRefereeData.updateRefereesPortalAllow())
    #asyncio.run(handleRefereeData.convertRefereeGamesReviewsToMobileNo())
    exit(0)
    #games = handleRefereeData.getRefereeGames(tenantKeys=['IL#football#2025-26'], mobileNo='+972547799979', includeArchived=True, fromDate=helpers.localNow() - timedelta(days=7), toDate=helpers.localNow() + timedelta(days=2))
    #result = handleRefereeData.findMostRelevantGames(mobileNo='43679', retry=0)
    
    asyncio.run(handleRefereeData.collectRefereesData())
    pass