import asyncio
import sys
import logging
import os
import uuid
import time
import re
#from dependency_injector import containers, providers
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytz
from ics import Calendar, Event
from ics.grammar.parse import ContentLine
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from shared.logger import Logger
from shared.db import CacheService
from shared.commonHelper import CommonHelper
from shared.orgRelated import OrgServiceFactory
from shared.messaging.messagingService import MessagingService

class HandleTournaments:
    def __init__(self, logger:Logger, cacheService:CacheService, commonHelper:CommonHelper, orgServiceFactory:OrgServiceFactory, messagingService:MessagingService):
        try:
            self.logger = logger
            self.cacheService = cacheService            
            self.commonHelper = commonHelper
            self.orgServiceFactory = orgServiceFactory
            self.messagingService = messagingService

            self.logger.info("🏆 HandleTournaments initialized with injected CacheService")

            self.translation_table = str.maketrans('', '', "!@#'? \"")
            self.dataDic = {
                "games" : {
                    "pkTags": [ "tournamentName", "gameTitle", "fixture" ],
                    "generate": self.commonHelper.generateGameDetails
                },
                "reviews": {
                    "pkTags": [ "tournamentName", "gameTitle", "fixture" ],
                    "generate": self.commonHelper.generateReviewDetails,
                },
                "gamesReports" : {
                    "pkTags": [ "tournamentName", "gameTitle", "fixture" ],
                }
            }

        except Exception as ex:
            self.logger.error(f"Error initializing HandleTournaments:", ex)
            pass

    def createTournament(self, tenantKey, tournamentName):
        tournament = {
            "tenantKey": tenantKey,
            "entityKey": tournamentName,
            "href": "",
            "leagueId": "",
            "rules": "",
            "section": "",
            "text": tournamentName,
            "tournament": "practice" if "אימון" in tournamentName else "cup" if "גביע" in tournamentName else "league",
            "tournamentName": tournamentName,
            }
        self.cacheService.setTournament(tenantKey=tenantKey, tournamentName=tournamentName, value=tournament)
        
        return tournament

    async def fix_women_leagues(self, leagueSection, leagueText):
        # Use cache service instead of loading from file
        sections = self.cacheService.getSections()
        if leagueSection == 'נשים':
            for section in sections:
                if section in leagueText:
                    leagueSection = section

        return leagueSection

    async def updateLeagues(self):
        leagues = jsonHelper.load_from_file('./data/tournaments/cups.json')
        for league in leagues:
            if leagues[league].get('tournament'):
                del leagues[league]['tournament']
            leagues[league]['tournament'] = 'cup'
        jsonHelper.save_to_file(leagues, './data/tournaments/cups.json')

    def createCalendar(self, games:list, mobileNo:str=None):
        try:
            gamesCalendar = Calendar()
            timestamp = int(time.time())
            firstGame = True
            games = games if games is not None else []
            for game in games:
                if not game:
                    continue
                if firstGame and mobileNo:
                    firstGame = False
                    calendarName = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', mobileNo=mobileNo, propertyName='calendarName')
                    if calendarName:
                        gamesCalendar.extra.append(ContentLine('X-WR-CALNAME', value=calendarName))
                gameDetail = self.cacheService.getGameDetail(tenantKey=game['tenantKey'], game=game)
                if not gameDetail:
                    self.logger.warning(f"createCalendar: skipping game with no detail tenantKey={game.get('tenantKey')}")
                    continue
                tenantKey = gameDetail['tenantKey']
                gameDesc = self.dataDic['games']['generate'](tenantKey=tenantKey, gameDetail=gameDetail, includeReferees=True)
                tournamentName = gameDetail['tournamentName']
                gameDurationInMins = self.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName)

                fieldName = gameDetail.get('field')
                location = ''
                if fieldName:
                    fieldValue = self.cacheService.get_field_by_name(tenantKey=tenantKey, fieldName=fieldName)
                    if fieldValue:
                        addr_details = fieldValue.get('addressDetails')
                        addr = addr_details.get('address', '') if isinstance(addr_details, dict) else ''
                        location = f"{fieldName}, {addr}" if addr else fieldName

                event = self.createCalendarEvent(
                            name=f"{gameDetail['gameTitle']}/{gameDetail['tournamentName']}",
                            begin=gameDetail['date'], \
                            durationInMins=gameDurationInMins, \
                            description=gameDesc, \
                            location=location, \
                            gameId=gameDetail['id'], \
                            removal=game.get('state', 'active') == 'removed'
                        )
                event.sequence = timestamp
                gamesCalendar.events.add(event)
            
            return gamesCalendar
        except Exception as ex:
            self.logger.error(f"Error creating calendar", ex)
            return None

    def createCalendarEvent(self, name, begin, durationInMins, description, location, gameId, removal=False):
        event = Event()
        event.uid = gameId
        localTZ = pytz.timezone(os.getenv('TZ'))
        # LAST-MODIFIED: so mobile/calendar clients know to update existing events
        event.last_modified = localTZ.localize(datetime.now())

        if removal:
            event.status = 'CANCELLED'
        else:
            event.name = name
            event.begin = localTZ.localize(begin)
            event.duration = timedelta(minutes=durationInMins)
            event.description = description
            event.location = location
            event.status = 'CONFIRMED'

        return event

    def calcGameDuration(self, tenantKey:str, tournamentName:str):
        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
        tenant = self.cacheService.get_tenant_by_key(tenantKey=tenantKey)
        gameDurationInMins = int(tenant.get('gameDurationInMins', '120'))
        if tournament and tournament.get('rules'):
            rules = self.cacheService.get_rule_by_name(tenantKey=tenantKey, ruleName=tournament['rules'].strip())
            if rules:
                gameDurationInMins = int(rules['gameGrossTime'])
                if tournament['tournament'] == 'cup':
                    gameDurationInMins += int(rules['cupGrossTime'])
                gameDurationInMins += 5
        
        return gameDurationInMins

    def sort():
        # Example list of dictionaries
        players = [
            {"name": "Alice", "score": 95},
            {"name": "Bob", "score": 85},
            {"name": "Charlie", "score": 90},
        ]

        # Sort by the 'score' property in ascending order
        sorted_players = sorted(players, key=lambda x: x['score'])
        print("Sorted by score (ascending):", sorted_players)

        # Sort by the 'score' property in descending order
        sorted_players_desc = sorted(players, key=lambda x: x['score'], reverse=True)
        print("Sorted by score (descending):", sorted_players_desc)

    def findTeamInTable(self, leagueTable, gameDetail, teamPropertyName):
        team = leagueTable.get(gameDetail[teamPropertyName].translate(self.translation_table))
        if not team:
            keys = list(team['קבוצה'] for team in leagueTable.values() if isinstance(team, dict))
            teamBestMatch = helpers.find_intuitive_matches(gameDetail[teamPropertyName], keys)
            if teamBestMatch:
                teams = list(team for team in leagueTable.values() if isinstance(team, dict) and team['קבוצה'] == teamBestMatch[0])
                if len(teams) == 1:
                    team = teams[0]
            else:
                teamBestMatch = helpers.find_intuitive_matches(gameDetail[teamPropertyName], leagueTable.keys())
                if teamBestMatch:
                    team = leagueTable.get(teamBestMatch.translate(self.translation_table))
        return team

    async def findGameTeamsInTable(self, tenantKey, gameDetail):
        tournamentName = gameDetail['tournamentName']
        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName)
        leagueTable = None
        homeTeam = None
        guestTeam = None
        if tournament and tournament['tournament'] == 'league' and self.cacheService.getLeagueTables(tenantKey=tenantKey, tournamentName=f"{tournament['text']}"):
            leagueTable = self.cacheService.getLeagueTables(tenantKey=tenantKey, tournamentName=f"{tournament['text']}")
            if leagueTable:
                #leagueTable = jsonHelper.json_loads(leagueTableDetails.get('value'))
                leagueTable = { team: teamStat for team, teamStat in leagueTable.items() if isinstance(teamStat, dict) }
                self.logger.debug(f'findGameTeamsInTable leagueTable={len(leagueTable)}')
                homeTeam = self.findTeamInTable(leagueTable=leagueTable, gameDetail=gameDetail, teamPropertyName='homeTeamName')
                guestTeam = self.findTeamInTable(leagueTable=leagueTable, gameDetail=gameDetail, teamPropertyName='guestTeamName')

                self.logger.debug(f"findGameTeamsInTable tournamentName={tournamentName} homeTeam={homeTeam} guestTeam={guestTeam}")
        
        return (tournament, leagueTable, homeTeam, guestTeam)

    def getPk(self, objType, obj):
        data = self.dataDic[objType]
        pk = ''
        for tag in data['pkTags']:
            pk += obj[tag].replace(':', '').replace('-', '')
        return pk

    async def updateTournamentGames(self, tenantKey, page, tournamentName, tournamentGames:dict):
        anyUpdate = False
        for gamePk, gameDetail in tournamentGames.items():
            gameDetail['gamePk'] = gamePk
            gameDetail['groupName'] = f'{gameDetail['tournamentName']} {gameDetail["gameTitle"]}'
            gameUrl = gameDetail['url']
            gameDetailFromDb = self.cacheService.getGameDetail(tenantKey=tenantKey, game=gameDetail) 
            if gameDetailFromDb:
                gameDetail = gameDetailFromDb
                if not gameDetail.get('url'):
                    gameDetail['url'] = gameUrl
                    self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                    self.logger.info(f'updateGameUrl groupName={gameDetail["groupName"]} gameUrl={gameUrl}')
            else:
                gameDetail['id'] = str(uuid.uuid4())[:8]
                gameDetail['reminders'] = {}
                gameDetail['groupMobileNumbers'] = ''
                self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
            
            if gameDetail.get('squads') and gameDetail.get('gameResult'):
                continue
            else:
                updated = await self.refreshTournamentGame(tenantKey=tenantKey, page=page, tournamentName=tournamentName, gameDetail=gameDetail)
                if updated:
                    anyUpdate = True
        return anyUpdate

    async def refreshTournamentGames(self, tenantKey, tournamentName=None, round1=None, fixture=None, fromFixture = None, fetchGamesUrls:bool = False, fetchGamesDetails:bool=False, fetchReferees:bool=False, tournamentTypes:list = ['league'], instance:int = None) -> (bool, str):
        helpers.stopwatchStart('refreshTournamentGames')
        orgService = self.orgServiceFactory.get_org_service_by_tenant(tenantKey=tenantKey)
        (result, message) = await orgService.refreshTournamentGames(tenantKey=tenantKey, tournamentName=tournamentName, round=round1, fixture=fixture, fromFixture=fromFixture, fetchGamesUrls=fetchGamesUrls, fetchGamesDetails=fetchGamesDetails, fetchReferees=fetchReferees, tournamentTypes=tournamentTypes, instance=instance)
        timeElapsed = helpers.stopwatchStop('refreshTournamentGames')
        await self.messagingService.sendMessage(to=self.messagingService.adminMobile, message=f"{helpers.localNow()} {tenantKey} {tournamentName} {message} {helpers.seconds_to_hms(round(timeElapsed/1000))}", title='עדכון משחקים')

        return result, message

    async def updateRules(self, tenantKey):
        rules = self.cacheService.getRules(tenantKey=tenantKey)
        for ruleId, rule in rules.items():
            matchSetup = {
                "templateName": "",           # or "ruleName" – template dropdown label
                "teamSize": 11,
                "subsNo": 7,
                "periodsNo": 2,                          # 1=one period, 2=halves, 3=thirds, 4=quarters
                "gameTime": int(rule.get('gameGrossTime', '80')),                     # total minutes; split by periodsNo if no periodLengths
                "periodLengths": None,#[40, 40],               # optional: minutes per period (overrides gameGrossTime)
                "intervalLengths": [15],                  # optional: minutes per interval (or interval1, interval2)
                "extraTimeAvailable": False,
                "extraTimeHalfLength": None,
                "penaltiesAvailable": False,
                "withGoalScorers": True,
                "sinBinSystem": "none",                  # "none" | "systemA" | "systemB"
                "misconductCodeId": "custom",             # e.g. "custom", "fifa", "england"
            }
            rule['matchSetup'] = matchSetup
            self.cacheService.setRule(tenantKey=tenantKey, ruleName=ruleId, value=rule)

    async def fixInvalidGamePks(self, tenantKey):
        tournaments = self.cacheService.getTournaments(tenantKey=tenantKey)
        for _tn, _t in tournaments.items():
            if _t.get('tournamentType') == 'league' and not _t.get('leagueId'):
                pass
            continue            
            updated = False
            toDelete = False
            games = self.cacheService.getTournamentGames(tenantKey=tenantKey, tournamentName=_tn)
            for _gp, _g in games.items():
                if len(_g) < 3:
                    continue
                try:
                    currentGamePk = _g.get('gamePk')
                    if 'live' in _g.get('homeTeamName'):
                        homeLines = _g.get('homeTeamName').split('\n')
                        _g['homeTeamName'] = homeLines[-1]
                        _g['gameTitle'] = _g.get('homeTeamName') + ' - ' + _g.get('guestTeamName')
                    if not _g.get('gameTitle'):
                        updated = True
                        _g['gameTitle'] = _g.get('homeTeamName') + ' - ' + _g.get('guestTeamName')
                    if not _g.get('fixture'):
                        updated = True
                        _g['fixture'] = re.search(r'\d+', _g['gamePk']).group(0)
                    gamePk = self.getPk(objType='games', obj=_g)
                    for prop in list(_g.keys()):
                        if _tn in prop:
                            updated = True
                            del _g[prop]
                    if currentGamePk and currentGamePk != gamePk:
                        updated = True
                        toDelete = True
                        _g['gamePk'] = gamePk
                    if updated:
                        self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=_tn, gamePk=gamePk, value=_g)
                    if toDelete:
                        self.cacheService.deleteTournamentGame(tenantKey=tenantKey, tournamentName=_tn, gamePk=currentGamePk)
                except Exception as ex:
                    pass

if __name__ == "__main__":
    from shared.appContainer import AppContainer
    container = AppContainer.getAppContainer()
    cacheService:CacheService = container.cache_service()
    from shared.handleTournaments import HandleTournaments
    handleTournaments:HandleTournaments = container.handle_tournaments()
    asyncio.run(handleTournaments.fixInvalidGamePks(tenantKey='IL#football#2025-26'))
    #asyncio.run(handleTournaments.updateRules(tenantKey='IL#football#2025-26'))
    #asyncio.run(handleTournaments.refreshTournamentGames(tenantKey='IL#football#2025-26', tournamentTypes=['league', 'cup']))

    pass
