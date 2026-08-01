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
from shared.db.repositories import TenantRepository
from shared.commonHelper import CommonHelper
from shared.orgRelated import OrgServiceFactory
from shared.messaging.messagingService import MessagingService

class HandleTournaments:
    def __init__(self, logger:Logger, cacheService:CacheService, commonHelper:CommonHelper, orgServiceFactory:OrgServiceFactory, messagingService:MessagingService, tenantRepository:TenantRepository=None):
        try:
            self.logger = logger
            self.cacheService = cacheService
            self.commonHelper = commonHelper
            self.orgServiceFactory = orgServiceFactory
            self.messagingService = messagingService
            self.tenantRepository = tenantRepository

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

    def _buildGameEventData(self, game: dict) -> dict | None:
        """Per-game fields shared by createCalendar (ICS feed) and getCalendarEventsData (JSON,
        for in-app EventKit import) - single source of truth so both stay consistent instead of
        duplicating the duration/description/location computation."""
        if not game:
            return None
        gameDetail = self.cacheService.getGameDetail(game=game)
        if not gameDetail:
            self.logger.warning(f"_buildGameEventData: skipping game with no detail tenantKey={game.get('tenantKey')}")
            return None
        tenantKey = gameDetail['tenantKey']
        gameDesc = self.dataDic['games']['generate'](tenantKey=tenantKey, gameDetail=gameDetail, includeReferees=True)
        tournamentName = gameDetail['tournamentName']
        gameDurationInMins = self.calcGameDuration(tenantKey=tenantKey, tournamentName=tournamentName, game=game)

        fieldName = gameDetail.get('fieldName')
        location = ''
        if fieldName:
            fieldValue = self.tenantRepository.get_field(tenant_key=tenantKey, field_name=fieldName)
            if fieldValue:
                location = f"{fieldName}, {fieldValue.address}" if fieldValue.address else fieldName

        return {
            'name': f"{gameDetail['gameTitle']}/{gameDetail['tournamentName']}",
            'begin': gameDetail['date'],
            'durationInMins': gameDurationInMins,
            'description': gameDesc,
            'location': location,
            'gameId': gameDetail['gameId'],
            'removal': game.get('state', 'active') == 'removed',
        }

    def createCalendar(self, games:list, refereeId:int=None):
        try:
            gamesCalendar = Calendar()
            timestamp = int(time.time())
            firstGame = True
            games = games if games is not None else []
            for game in games:
                if firstGame and refereeId:
                    firstGame = False
                    calendarName = self.cacheService.getRefereeProperty(tenantKey='GLOBAL', refereeId=refereeId, propertyName='calendarName')
                    if calendarName:
                        gamesCalendar.extra.append(ContentLine('X-WR-CALNAME', value=calendarName))
                eventData = self._buildGameEventData(game)
                if not eventData:
                    continue
                event = self.createCalendarEvent(**eventData)
                event.sequence = timestamp
                gamesCalendar.events.add(event)

            return gamesCalendar
        except Exception as ex:
            self.logger.error(f"Error creating calendar", ex)
            return None

    def getCalendarEventsData(self, games: list) -> list[dict]:
        """JSON-serializable per-game event data for in-app EventKit import (normal authenticated
        API call, unlike createCalendar's ICS feed which is fetched via a URL-embedded token so
        OS Calendar apps / WhatsApp links can subscribe without custom headers)."""
        games = games if games is not None else []
        results = []
        for game in games:
            eventData = self._buildGameEventData(game)
            if not eventData:
                continue
            begin = self._naive_local_datetime(eventData['begin'])
            results.append({
                'name': eventData['name'],
                'begin': begin.isoformat(),
                'durationInMins': eventData['durationInMins'],
                'description': eventData['description'],
                'location': eventData['location'],
                'gameId': eventData['gameId'],
                'removal': eventData['removal'],
            })
        return results

    def _naive_local_datetime(self, value):
        # gameDetail['date'] can be a datetime (cold cache, straight from Postgres) or a string
        # like "2026-07-12 11:00:00+03:00" (round-tripped through the Redis JSON cache) - and
        # either shape may carry a tzinfo/offset that's already local (never UTC, for this data),
        # not naive. pytz's localize() requires naive, so strip any tzinfo rather than convert -
        # the wall-clock value is already correct local time either way (mirrors
        # ScheduleAgent._game_datetime_value's handling of the same cache-shape inconsistency).
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        s = str(value).strip()
        return datetime.fromisoformat(s.split('+')[0]).replace(tzinfo=None)

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
            event.begin = localTZ.localize(self._naive_local_datetime(begin))
            event.duration = timedelta(minutes=durationInMins)
            event.description = description
            event.location = location
            event.status = 'CONFIRMED'

        return event

    def calcGameDuration(self, tenantKey:str, tournamentName:str, game:dict=None):
        tournament = self.cacheService.get_tournament_by_name(tenantKey=tenantKey, tournamentName=tournamentName, game=game)
        tenant = self.tenantRepository.get_tenant(tenant_key=tenantKey, game=game)
        gameDurationInMins = tenant.game_duration_in_mins if tenant else 120
        if tournament and tournament.get('rules'):
            rules = self.tenantRepository.get_rule(tenant_key=tenantKey, rule_name=tournament['rules'].strip())
            if rules and rules.game_gross_time:
                gameDurationInMins = rules.game_gross_time
                if tournament['tournament'] == 'cup' and rules.cup_gross_time:
                    gameDurationInMins += rules.cup_gross_time
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
        tournamentName = gameDetail.get('tournamentName')
        if not tournamentName:
            return (None, None, None, None)
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
            gameDetail.setdefault('tenantKey', tenantKey)
            gameDetailFromDb = self.cacheService.getGameDetail(game=gameDetail)
            if gameDetailFromDb:
                gameDetail = gameDetailFromDb
                if not gameDetail.get('url'):
                    gameDetail['url'] = gameUrl
                    self.cacheService.setTournamentGame(tenantKey=tenantKey, tournamentName=tournamentName, gamePk=gamePk, value=gameDetail)
                    self.logger.info(f'updateGameUrl groupName={gameDetail["groupName"]} gameUrl={gameUrl}')
            else:
                gameDetail['id'] = str(uuid.uuid4())[:8]
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
