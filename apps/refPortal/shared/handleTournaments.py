from playwright.async_api import async_playwright
import asyncio
from urllib.parse import urlparse, parse_qs
import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
import shutil
from datetime import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
from shared.handleRefereeData import HandleRefereeData

class HandleTournaments:
    def __init__(self, logger):
        try:
            '''
            self.app = os.environ.get('app')

            logLevel = eval(f"logging.{os.environ.get('logLevel') or 'DEBUG'}")
            logFormat = f'%(asctime)s - {self.app} - %(name)s - %(levelname)s - %(message)s'
            formatter = logging.Formatter(logFormat)
            logging.basicConfig(level=logLevel, format=logFormat)
            self.logger = logging.getLogger(__name__)

            logFile = f'{os.getenv("MY_DATA_FILE", "/run/data/")}logs/log{__name__}-{self.app}.log'
            file_handler = TimedRotatingFileHandler(
                logFile, when="H", interval=1, backupCount=6, encoding="utf-8"
            )        
            #file_handler = logging.FileHandler(logFile)
            file_handler.setLevel(logging.DEBUG)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(logLevel) 

            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            self.logger.handlers.clear()
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
            '''
            self.logger = logger
            self.protocol = 'https://'
            self.baseIFAUrl = 'www.football.org.il'
            self.baseVoleUrl = 'vole.one.co.il'
            self.translation_table = str.maketrans('', '', "!@#'? \"")

            self.handleRefereeData = HandleRefereeData(self.logger)
            self.leagueTableFileChanged = {}
        except Exception as ex:
            pass
            
    async def scrapVoleLeagues(self, page):
        sections = helpers.load_from_file('./data/tournaments/sections.json')   
        tournaments = helpers.load_from_file('./data/tournaments/tournaments.json')
        leagueRows = page.locator('a.animated')
        leagueRows = [(leagueRows.nth(i)) for i in range(await leagueRows.count())]
        for leagueRow in leagueRows:
            leagueName = (await leagueRow.inner_text()).strip()
            league = tournaments.get(leagueName)
            if not league:
                league = tournaments.get(leagueName.replace('טרום','ילדים טרום'))
            if not league:
                continue
            if league.get('table'):
                del league['table']
            section = sections[league['section']]
            if section['tableResult'] != 'Vole':
                continue
            leagueVoleUrl = await leagueRow.get_attribute('href')
            league['voleHref'] = f'{leagueVoleUrl}'
        
        helpers.save_to_file(tournaments ,'./data/tournaments/tournaments.json')

        #await scrapVoleLeaguesData(page)

    async def scrapVoleLeaguesData(self, page):
        leaguesList = helpers.load_from_file('./data/tournaments/tournaments.json')
        sections = helpers.load_from_file('./data/tournaments/sections.json')

        for leagueName in leaguesList:
            league = leaguesList[leagueName]
            if not league.get('voleHref'):
                continue
            if sections[league['section']]['tableResult'] == 'Vole':
                leagueData = await self.getVoleLeagueData(page, league['voleHref'])
                league['table'] = leagueData
                helpers.save_to_file(leaguesList, './data/tournaments/tournaments.json')

            print (f'{league} => {len(leagueData)}')

        #helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

    async def scrapLeaguesData(self, page):
        leaguesList = helpers.load_from_json('./data/tournaments/tournaments.json')
        sections = helpers.load_from_json('./data/tournaments/sections.json')

        for league in leaguesList:
            leagueData = await self.getIFALeagueData(page, leaguesList[league]['href'])
            if sections[leaguesList[league]['section']]['tableResult'] == True:
                leaguesList[league]['table'] = leagueData
                helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

            print (f'{league} => {len(leagueData)}')

        #helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

    async def scarpCupList(self, page, submenu_locator):
        sections = helpers.load_from_file('./data/tournaments/sections.json')
        submenu_items = await submenu_locator.query_selector_all("li")
        cupsList = []
        cups = {}
        cupSection = None
        for item in submenu_items:
            text = (await item.inner_text()).strip()
            link = await item.query_selector("a")
            href = await link.get_attribute("href") if link else None
            query = urlparse(href).query
            params = parse_qs(query)
            nationalCupId = int(params.get('national_cup_id', 0)[0])
            name = text
            if nationalCupId == 0:
                cupSection = text[:text.find('\n')]
                #cupSection = await fix_women_leagues(leagueSection, text)
            else:
                cupsList.append({ 'text': text, 'section': cupSection, 'nationalCupId': nationalCupId, 'rules': '', 'href': href})

        for cup in cupsList:
            name = await self.getLeagueName(page, cup['href'])
            #leagueData = await getLeagueData(page, cup['href'])
            cups[name] = cup
            #if sections[cup['section']]['tableResult'] == True:
            #    cups[name]['table'] = leagueData

            print (f'{name}')
        
        return cups

    async def getCupsList(self):
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            # Open the URL
            await helpers.gotoUrl(page, f'{self.protocol}{self.baseIFAUrl}')

            # Wait for the submenu to be visible
            submenu_locator = (await page.query_selector_all("ul.second-level-list"))[3]
            #submenu_locator = await page.wait_for_selector("ul.submenu")

            # Scan all submenu items
            cupsList = await self.scarpCupList(page, submenu_locator)

            #cupsList = helpers.load_from_json('./data/tournaments/cups.json')

            # Output the collected data
            for cup in cupsList:
                print(f"Text: {cup}, Link: {cupsList[cup]['href']}")

            # Close the browser
            await browser.close()

            helpers.save_to_file(cupsList, './data/tournaments/cups.json')

    async def getLeaguesList(self):
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            # Open the URL
            await helpers.gotoUrl(page, f'{self.protocol}{self.baseIFAUrl}')

            # Wait for the submenu to be visible
            submenu_locator = (await page.query_selector_all("ul.second-level-list"))[2]
            #submenu_locator = await page.wait_for_selector("ul.submenu")

            # Scan all submenu items
            #await scarpLeaguesList(page, submenu_locator)
            await self.scrapLeaguesData(page)

            leaguesList = helpers.load_from_json('./data/tournaments/tournaments.json')

            # Output the collected data
            for league in leaguesList:
                print(f"Text: {league}, Link: {leaguesList[league]['href']}")

            # Close the browser
            await browser.close()

            helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

    async def fix_women_leagues(self, leagueSection, leagueText):
        sections = helpers.load_from_json('./data/tournaments/sections.json')
        if leagueSection == 'נשים':
            for section in sections:
                if section in leagueText:
                    leagueSection = section

        return leagueSection

    async def getLeagueName(self, page, tournamentUrl):
        if page.url != f'{self.protocol}{self.baseIFAUrl}{tournamentUrl}':
            await helpers.gotoUrl(page, f'{self.protocol}{self.baseIFAUrl}{tournamentUrl}', timeout=15000)
        tableTitle = await page.query_selector_all('span.big')
        if tableTitle and len(tableTitle) == 1: 
            return (await tableTitle[0].inner_text()).strip()
        return None

    async def getVoleTableData(self, page):
        table_data = {}
        tableTitle = await page.query_selector_all('h1')
        if tableTitle: 
            div = await page.query_selector_all("div.standings_container__Dm8WX")
            if not div:
                print(f"No element found with selector: {'div.standings_container__Dm8WX'}")
                return table_data

            headMapping = [
                "מעבר",
                "מיקום",
                "קבוצה",
                "משחקים",
                "ניצחונות",
                "תיקו",
                "הפסדים",
                "שערים",
                "הפרש",
                "נקודות",
            ]
            headMapping1 = {
                "מיקום": "מיקום",
                "קבוצה": "קבוצה",
                "מש׳": "משחקים",
                "נצ׳": "ניצחונות",
                "ת׳": "תיקו",
                "הפ׳": "הפסדים",
                "יחס": "שערים",
                "הפרש": "הפרש",
                "נק׳": "נקודות",
            }
            # Find all rows in the table within the div
            theadTr = await div[0].query_selector_all("thead tr th")
            tbody = await div[0].query_selector_all("tbody")
            rows = await tbody[0].query_selector_all("tr")
            for row in rows:
                elements = await row.query_selector_all("td")
                cells = {}
                i = -1
                for cell in elements:
                    i += 1
                    if i == 0:
                        continue
                    cell = elements[i]
                    head = headMapping[i]
                    '''
                    if i == 0:
                        head = 'מיקום'
                    else:
                        head = await theadTr[i-1].inner_text()
                    '''
                    obj = (await cell.inner_text()).strip()
                    if False and headMapping.get(head):
                        head = headMapping[head]
                    cells[head] = obj
                teamName = cells['קבוצה'].translate(self.translation_table)
                table_data[teamName] = cells

        return table_data

    async def getIFATableData(self, page):
        table_data = {}

        roundLocator = page.locator(f"select#ddlBoxes")
        if roundLocator and await roundLocator.count() == 1:
            roundOptions = roundLocator.locator('option')
            roundOptionsTexts = [await roundOptions.nth(i).text_content() for i in range(await roundOptions.count())]
            
            for roundOptionText in roundOptionsTexts:
                await roundLocator.select_option(label=roundOptionText, timeout=15000)
                await asyncio.sleep(100/1000)

                tableTitle = await page.query_selector_all('h2#LEAGUE_TABLE_TITLE_PLAYOFF')
                if tableTitle: 
                    full_view_div = await page.query_selector_all("div.vertical-title")
                    if not full_view_div:
                        print(f"No element found with selector: {'div.vertical-title'}")
                        return table_data

                    # Find all rows in the table within the div
                    rows = await full_view_div[0].query_selector_all("a.table_row")
                    for row in rows:
                        # Extract all cell data (th or td)
                        elements = await row.query_selector_all("a, div")
                        cells = {}
                        href = await row.get_attribute("href")
                        cells['href'] = href
                        query = urlparse(href).query
                        params = parse_qs(query)
                        teamId = int(params.get('team_id', 0)[0])
                        cells['teamId'] = teamId
                        for cell in elements:
                            obj = (await cell.inner_text()).strip().split('\n')
                            cells[obj[0]] = obj[1]
                        teamName = cells['קבוצה'].translate(self.translation_table)
                        table_data[teamName] = cells

        return table_data

    async def getVoleLeagueData(self, page, voleUrl):
        table_data = {}
        t = 0
        while table_data == {} and t < 2:
            try:
                if page.url != f'{self.protocol}{self.baseVoleUrl}{voleUrl}':
                    await helpers.gotoUrl(page, f'{self.protocol}{self.baseVoleUrl}{voleUrl}', timeout=15000)
                await asyncio.sleep(50/1000)
                table_data = await self.getVoleTableData(page)
            except Exception as e:
                pass
            finally:
                pass

            t = t + 1

        return table_data

    async def getIFALeagueData(self, page, tournamentUrl):
        table_data = {}
        t = 0
        while table_data == {} and t < 2:
            try:
                if page.url != f'{self.protocol}{self.baseIFAUrl}{tournamentUrl}':
                    await helpers.gotoUrl(page, f'{self.protocol}{self.baseIFAUrl}{tournamentUrl}', timeout=15000)
                await asyncio.sleep(50/1000)
                table_data = await self.getIFATableData(page)
            except Exception as e:
                pass
            finally:
                pass

            t = t + 1

        return table_data

    async def updateLeagues(self):
        leagues = helpers.load_from_file('./data/tournaments/cups.json')
        for league in leagues:
            if leagues[league].get('tournament'):
                del leagues[league]['tournament']
            leagues[league]['tournament'] = 'cup'
        helpers.save_to_file(leagues, './data/tournaments/cups.json')

    async def refreshLeagueTable(self, page, tournament, section):
        if tournament['tournament'] == 'cup':
            return
        #print(f"league={tournament} --> {section['tableResult']}")
        leagueTable = None
        if section['tableResult'] == 'IFA':
            leagueTable = await self.getIFALeagueData(page, tournament['href'])
        elif section['tableResult'] == 'Vole':
            if tournament.get('voleHref'):
                leagueTable = await self.getVoleLeagueData(page, tournament['voleHref'])
        if leagueTable or False:
            if tournament.get('table'):
                del tournament['table']
            print(f'league={tournament} rows={len(leagueTable)}')

            tableFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/leagueId{tournament["leagueId"]}.json'
            if os.path.exists(tableFilePath):
                fileDateTime = datetime.fromtimestamp(os.path.getmtime(tableFilePath)).strftime("%Y%m%d%H%M%S")
                shutil.copy(tableFilePath,f'{tableFilePath}_{fileDateTime}' )
            helpers.save_to_file(leagueTable, tableFilePath)

    async def refreshLeaguesTables(self, forceLoad = True, leagueName = None):
        sections = helpers.load_from_file(f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/sections.json')
        tournaments = helpers.load_from_file(f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tournaments.json')
        found = False
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            for tournamentName in tournaments:
                tournament = tournaments[tournamentName]
                if leagueName and leagueName != tournamentName:
                    continue
                if sections.get(tournament.get('section')):
                    found = True
                    await self.refreshLeagueTable(page, tournament, sections[tournament.get('section')])

            await browser.close()

        return found

    async def getGameUrl(self, page, tournament, round, fixture, homeTeamId, guestTeamId, homeTeamName, guestTeamName):
        try:
            aRow = None
            url = f"{self.protocol}{self.baseIFAUrl}{tournament['href']}"
            await helpers.gotoUrl(page, url)        
            fixtureOptionText = f'מחזור {fixture}'

            try:
                roundLocator = page.locator(f"select#ddlBoxes")
                if roundLocator and await roundLocator.count() == 1:
                    roundOptions = roundLocator.locator('option')
                    roundOptionsTexts = [await roundOptions.nth(i).text_content() for i in range(await roundOptions.count())]
                    
                    for roundOptionText in roundOptionsTexts:
                        if True or f'סבב {round}' in roundOptionsTexts:
                            await roundLocator.select_option(label=roundOptionText, timeout=15000)
                            await asyncio.sleep(100/1000)
                        fixtureLocator = page.locator(f"select#ddlRounds")            
                        if fixtureLocator and await fixtureLocator.count() == 1:     
                            fixtureOptions = fixtureLocator.locator('option')
                            fixtureOptionsTexts = [await fixtureOptions.nth(i).text_content() for i in range(await fixtureOptions.count())]
                            if fixtureOptionText in fixtureOptionsTexts:
                                await fixtureLocator.select_option(label=fixtureOptionText, timeout=15000)
                                await asyncio.sleep(300/1000)
                                #fixtureTitleLocator = page.locator('div.table_data_header')
                                #fixtureTitle = await (fixtureTitleLocator.nth(0)).inner_text()
                    
                        if homeTeamId:
                            selector = f".table_row[data-team1='{homeTeamId}'][data-team2='{guestTeamId}']"
                            aRowsLocator = page.locator(f"a{selector}")
                            if aRowsLocator and await aRowsLocator.count() == 1:
                                aRow = aRowsLocator.nth(0)
                                break

                        else:
                            resultsDivLocator = page.locator(f"div.results-grid")
                            cnt = await resultsDivLocator.count()
                            if cnt == 0:
                                return None

                            for i in range(cnt):
                                resultGridLocator = resultsDivLocator.nth(i)
                                gamesRowsLocator = resultGridLocator.locator("a.table_row")
                                games = [(gamesRowsLocator.nth(i)) for i in range(await gamesRowsLocator.count())]
                                for game in games:
                                    gameText = await game.inner_text()
                                    if homeTeamName in gameText and guestTeamName in gameText:
                                        aRow = game
                                        break
                                if aRow:
                                    break

            except Exception as ex:
                pass

            if aRow:
                url = f'{self.protocol}{self.baseIFAUrl}{await aRow.get_attribute("href")}'
                self.logger.debug(f"getGameUrl tournamet={tournament['text']} round={round} fixture={fixture} homeTeamId={homeTeamId} guestTeamId={guestTeamId} homeTeamName={homeTeamName} guestTeamName={guestTeamName} url={url}")
                self.logger.info(f'המשחק {homeTeamName} נגד {guestTeamName} פורסם')
                return url
            
        except Exception as ex:
            self.logger.error(f'Error in getGameUrl {url} {ex}')
        
        return None

    async def scrapTeamSectionDetails(self, page, ariaAttributeValue, coach = False):
        div = page.locator(f"div[aria-labelledby='{ariaAttributeValue}']")

        #div = page.locator(f"div{ariaAttributeValue}")

        # Ensure the div exists before continuing
        if await div.count() == 0:
            return None

        # Select all spans under divs with the class 'player'
        playerSpans = div.locator("div.player span, div.player b")
        spansText = []
        for i in range(await playerSpans.count()):
            playerSpan = playerSpans.nth(i)
            playerSpanChildren = playerSpan.locator(":scope > *")
            c = await playerSpanChildren.count()
            text = await playerSpan.inner_text()
            if coach and c > 0:
                continue
            spansText.append(text)
        #spansText = [(await playerSpans.nth(i).inner_text()) for i in range(await playerSpans.count())]
        return spansText

    def parsePlayersSpans(self, playersSpans):
        players = {}
        player = {}

        if playersSpans:
            for span in playersSpans:
                if "מס'" in span:
                    no = int(span.replace("מס'", "").strip())
                    player = { 'no': no }
                    players[no] = player
                elif len(player) <= 1:
                    name = span
                    if "- (GK)" in name:
                        name = name.replace("- (GK)", "").strip()
                        player['gk'] = True 
                    if "- (C)" in name:
                        name = name.replace("- (C)", "").strip()
                        player['c'] = True 
                    player['name'] = name
                elif span == '':
                    continue
                else:
                    arr = span.split('\n')
                    if len(arr) < 3:
                        continue
                    if arr[0] == "יצא":
                        player['subOut'] = int(arr[2])
                    elif arr[0] == "נכנס":
                        player['subIn'] = int(arr[2])
                    if arr[0] == "כרטיס צהוב":
                        player['yellowCard'] = int(arr[2])
                    elif arr[0] == "כרטיס אדום":
                        player['subIn'] = int(arr[2])
            
        return players

    def formatPlayers(self, players):
        sortedPlayers = dict(sorted(players.items(), key=lambda player: player[1]['no']))
        captainPlayer = next((key for key, value in players.items() if value.get('c') == True), None)
        goalkeeperPlayer = next((key for key, value in players.items() if value.get('gk') == True), None)
        formatedPlayers = []
        if captainPlayer:
            formatedPlayers.append(str(captainPlayer))
        if goalkeeperPlayer:
            formatedPlayers.append(str(goalkeeperPlayer))
        formatedPlayers += [f"{sortedPlayers[playerNo]['no']}" for playerNo in sortedPlayers  if (not captainPlayer or playerNo != captainPlayer) and (not goalkeeperPlayer or playerNo != goalkeeperPlayer)]
        return formatedPlayers

    def loadLeagueTable(self, filePath, file):
        leagueId = file[file.find('leagueId')+8:].rstrip('.json')
        if not leagueId.isdigit():
            return
        fullPath = f'{filePath}{file}'
        if os.path.exists(fullPath):
            self.tournamentsTables[leagueId] = helpers.load_from_file(fullPath)
            self.logger.info(f'refresh table leagueId={leagueId} #teams={len(self.tournamentsTables[leagueId])}...')

    def loadTournaments(self, filePath, file=None, initial=False):
        self.logger.info('load tournaments...')
        self.tournaments = helpers.load_from_file(filePath)

        gamesFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/games/'
        self.tournamentsTables = {}
        self.tournamentsById = {}
        if initial:
            self.logger.info('load tournaments tables...')
        for tournamentName in self.tournaments:
            tournament = self.tournaments[tournamentName]
            if tournament.get('leagueId'):
                leagueId = str(tournament["leagueId"])
                id = f'leagueId{leagueId}'
                if initial or self.leagueTableFileChanged.get(leagueId):
                    filePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/'
                    self.loadLeagueTable(filePath, f'leagueId{leagueId}.json')
            else:
                id = f'nationalCupId{tournament["nationalCupId"]}'
            self.tournamentsById[id] = tournament
            if initial:
                self.loadGames(gamesFilePath, f'{id}.json')
        pass

    def loadGames(self, filePath=None, file=None):
        id = file.rstrip('.json')
        if not self.tournamentsById.get(id):
            return
        tournament = self.tournamentsById[id]
        games = helpers.load_from_file(f'{filePath}{file}')
        self.logger.info(f'load games {file}={len(games)}...')
        tournament['games'] = games

    def writeGame(self, gamePk, tournamentName, gameDetail):
        tournament = self.tournaments[tournamentName]
        if tournament.get('leagueId'):
            id = f"leagueId{tournament['leagueId']}"
        else:
            id = f"nationalCupId{tournament['nationalCupId']}"
        if not tournament.get('games'):
            tournament['games'] = {}     
        tournament['games'][gamePk] = gameDetail
        gamesFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/games/{id}.json'
        helpers.save_to_file(tournament['games'], gamesFilePath)

    async def scrapGameDetails(self, page, url, gameId, tournamentName):
        # Navigate to the URL
        await helpers.gotoUrl(page, url)

        homeActiveSpans = await self.scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_ACTIVE_HOME')
        homeReplacementSpans = await self.scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Replacement_HOME')
        homeBenchSpans = await self.scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Bench_HOME')
        homeCoachSpans = await self.scrapTeamSectionDetails(page, 'GAME_COACH_HOME', True)
        awayActiveSpans = await self.scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_ACTIVE_GUEST')
        awayReplacementSpans = await self.scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Replacement_GUEST')
        awayBenchSpans = await self.scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Bench_GUEST')
        awayCoachSpans = await self.scrapTeamSectionDetails(page, 'GAME_COACH_GUEST', True)

        homeActivePlayers = self.parsePlayersSpans(homeActiveSpans)
        homeReplacementPlayers = self.parsePlayersSpans(homeReplacementSpans)
        homeBenchPlayers = self.parsePlayersSpans(homeBenchSpans)
        homeCoach = homeCoachSpans[1] if homeCoachSpans else ''
        awayActivePlayers = self.parsePlayersSpans(awayActiveSpans)
        awayReplacementPlayers = self.parsePlayersSpans(awayReplacementSpans)
        awayBenchPlayers = self.parsePlayersSpans(awayBenchSpans)
        awayCoach = awayCoachSpans[1] if awayCoachSpans else ''

        formatedHomeActivePlayers = self.formatPlayers(homeActivePlayers)
        homeActivePlayersNos = ','.join(formatedHomeActivePlayers)
        formatedHomeReplacementPlayers = self.formatPlayers(homeReplacementPlayers)
        homeReplacementPlayersNos = ','.join(formatedHomeReplacementPlayers)
        formatedHomeBenchPlayers = self.formatPlayers(homeBenchPlayers)
        homeBenchPlayersNos = ','.join(formatedHomeBenchPlayers)
        formatedAwayActivePlayers = self.formatPlayers(awayActivePlayers)
        awayActivePlayersNos = ','.join(formatedAwayActivePlayers)
        formatedAwayReplacementPlayers = self.formatPlayers(awayReplacementPlayers)
        awayReplacementPlayersNos = ','.join(formatedAwayReplacementPlayers)
        formatedAwayBenchPlayers = self.formatPlayers(awayBenchPlayers)
        awayBenchPlayersNos = ','.join(formatedAwayBenchPlayers)
 
        squads = { 'homeActivePlayers': homeActivePlayers, 'homeReplacementPlayers': homeReplacementPlayers, 'homeBenchPlayers': homeBenchPlayers, 'homeCoach': homeCoach, \
                    'homeActivePlayersNos': homeActivePlayersNos, 'homeReplacementPlayersNos': homeReplacementPlayersNos, 'homeBenchPlayersNos': homeBenchPlayersNos, \
                    'awayActivePlayers': awayActivePlayers, 'awayReplacementPlayers': awayReplacementPlayers, 'awayBenchPlayers': awayBenchPlayers, 'awayCoach': awayCoach, \
                    'awayActivePlayersNos': awayActivePlayersNos, 'awayReplacementPlayersNos': awayReplacementPlayersNos, 'awayBenchPlayersNos': awayBenchPlayersNos }
        
        gameDetail = { 'url': url, 'squads': squads }
        self.writeGame(gameId, tournamentName, gameDetail)

        return squads

    async def createSections(self):
        leagues = helpers.load_from_json('./data/tournaments/tournaments.json')
        sections = {}
        for league in leagues:
            section = league['section']
            if section not in sections:
                sections[section] = { "tableResult": False}
                continue

        helpers.save_to_json(sections, './data/tournaments/sections.json')

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

    async def approveGame(self, refereeDetail, gameId, statusCell, page):
        try:
            self.logger.info(f'approveGame refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
            if statusCell:
                await statusCell.click()
                inputsLocators = page.locator("input.circle[name='confirm']")
                if await inputsLocators.count() == 2:
                    await inputsLocators.nth(0).click()
                    noteInputLocator = page.locator("input.custom-input[name='note']")
                    if await noteInputLocator.count() == 1:
                        await noteInputLocator.nth(0).fill(f'אושר')
                    confirmButtonLocator = page.locator("button.btn").filter(has_text="אישור")                
                    if await confirmButtonLocator.count() == 1:
                        await confirmButtonLocator.nth(0).click()
                        return True

            return False
        except Exception as ex:
            self.logger.error(f'approveGame error: {ex}')

    async def findGameTeamsInTable(self, game):
        tournamentName = game['מסגרת משחקים']
        tournament = self.tournaments.get(tournamentName)
        leagueTable = None
        homeTeam = None
        guestTeam = None
        if tournament and tournament['tournament'] == 'league' and self.tournamentsTables.get(f"{tournament['leagueId']}"):
            leagueTable = self.tournamentsTables[f"{tournament['leagueId']}"]
            self.logger.debug(f'findGameTeamsInTable leagueTable={len(leagueTable)}')
            homeTeam = leagueTable.get(game['homeTeamName'].translate(self.translation_table))
            if not homeTeam:
                homeTeamBestMatch = helpers.find_best_match(game['homeTeamName'], leagueTable.keys())
                if homeTeamBestMatch:
                    homeTeam = leagueTable.get(homeTeamBestMatch.translate(self.translation_table))
            guestTeam = leagueTable.get(game['guestTeamName'].translate(self.translation_table))
            if not guestTeam:
                guestTeamBestMatch = helpers.find_best_match(game['guestTeamName'], leagueTable.keys())
                if guestTeamBestMatch:
                    guestTeam = leagueTable.get(guestTeamBestMatch.translate(self.translation_table))

        self.logger.debug(f"findGameTeamsInTable tournamentName={tournamentName} homeTeam={homeTeam} guestTeam={guestTeam}")
        return (tournament,leagueTable, homeTeam, guestTeam)

    async def openBrowser(self):
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            tournaments_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/tournaments.json'
            self.loadTournaments(tournaments_file_path)
            file_path = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/gamesProd.json'
            games = helpers.load_from_file(file_path)
            newGames = {}
            for gameId in games:
                game = games[gameId]
                tournamentName = game[:gameId.find(' ')]
                tournament = self.tournaments[tournamentName]
                '''
                game['squads'] = game['squads']['squads']
                squads = game['squads']
                homeActivePlayersNos = ','.join(squads['formatedHomeActivePlayers'])
                homeReplacementPlayersNos = ','.join(squads['formatedHomeReplacementPlayers'])
                homeBenchPlayersNos = ','.join(squads['formatedHomeBenchPlayers'])
                awayActivePlayersNos = ','.join(squads['formatedAwayActivePlayers'])
                awayReplacementPlayersNos = ','.join(squads['formatedAwayReplacementPlayers'])
                awayBenchPlayersNos = ','.join(squads['formatedAwayBenchPlayers'])
                del squads['formatedHomeActivePlayers']
                del squads['formatedHomeReplacementPlayers']
                del squads['formatedHomeBenchPlayers']
                del squads['formatedAwayActivePlayers']
                del squads['formatedAwayReplacementPlayers']
                del squads['formatedAwayBenchPlayers']
                squads['homeActivePlayersNos'] = homeActivePlayersNos
                squads['homeReplacementPlayersNos'] = homeReplacementPlayersNos
                squads['homeBenchPlayersNos'] = homeBenchPlayersNos
                squads['awayhomeActivePlayersNos'] = awayActivePlayersNos
                squads['awayReplacementPlayersNos'] = awayReplacementPlayersNos
                squads['awayBenchPlayersNos'] = awayBenchPlayersNos
                '''
                squads = await self.scrapGameDetails(page, game['url'], gameId, tournamentName)

            #helpers.save_to_file(games, f'{file_path}')
            #await scrapVoleLeagues(page)
            pass
            #asyncio.run(refreshLeaguesTables())

            browser.close

    async def openBrowser1(self):
        async with async_playwright() as p:                
            browser = await p.firefox.launch(headless=True)
            page = await browser.new_page()

            tournaments_file_path = f'{os.getenv("MY_DATA_FILE", "/run/data/")}tournaments/tournaments.json'
            self.loadTournaments(tournaments_file_path, None, True)
            refereeData = {
                "refId": "43667",
                "currentList": {},
                "prevList": {}
            }
            await self.handleRefereeData.readRefereeDataFile('games', refereeData)
            for gameId in refereeData['games']['currentList']:
                game = refereeData['games']['currentList'][gameId]
                (tournament, leagueTable, homeTeam, guestTeam) = await self.findGameTeamsInTable(game)
                if tournament:
                    url = await self.getGameUrl(page, tournament, game['סבב'], game['מחזור'], homeTeam.get('teamId') if homeTeam else None, guestTeam.get('teamId') if guestTeam else None, game['homeTeamName'], game['guestTeamName'])
                pass
if __name__ == "__main__":
    handleTournaments = HandleTournaments()
    #asyncio.run(refreshLeaguesTables())
    #asyncio.run(handleTournaments.openBrowser())
    asyncio.run(handleTournaments.openBrowser1())

    pass
