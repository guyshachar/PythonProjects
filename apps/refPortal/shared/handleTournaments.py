from playwright.async_api import async_playwright
import asyncio
from urllib.parse import urlparse, parse_qs
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers

baseIFAUrl = "https://www.football.org.il"
baseVoleUrl = "https://vole.one.co.il"
translation_table = str.maketrans('', '', "!@#'? \"")

async def scrapVoleLeagues(page):
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
        leagueVoleUrl = await leagueRow.get_attribute("href")
        league['voleHref'] = f'{leagueVoleUrl}'
    
    helpers.save_to_file(tournaments ,'./data/tournaments/tournaments.json')

    #await scrapVoleLeaguesData(page)

async def scrapVoleLeaguesData(page):
    leaguesList = helpers.load_from_file('./data/tournaments/tournaments.json')
    sections = helpers.load_from_file('./data/tournaments/sections.json')

    for leagueName in leaguesList:
        league = leaguesList[leagueName]
        if not league.get('voleHref'):
            continue
        if sections[league['section']]['tableResult'] == 'Vole':
            leagueData = await getVoleLeagueData(page, league['voleHref'])
            league['table'] = leagueData
            helpers.save_to_file(leaguesList, './data/tournaments/tournaments.json')

        print (f'{league} => {len(leagueData)}')

    #helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

async def scrapLeaguesData(page):
    leaguesList = helpers.load_from_json('./data/tournaments/tournaments.json')
    sections = helpers.load_from_json('./data/tournaments/sections.json')

    for league in leaguesList:
        leagueData = await getIFALeagueData(page, leaguesList[league]['href'])
        if sections[leaguesList[league]['section']]['tableResult'] == True:
            leaguesList[league]['table'] = leagueData
            helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

        print (f'{league} => {len(leagueData)}')

    #helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

async def scarpCupList(page, submenu_locator):
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
        name = await getLeagueName(page, cup['href'])
        #leagueData = await getLeagueData(page, cup['href'])
        cups[name] = cup
        #if sections[cup['section']]['tableResult'] == True:
        #    cups[name]['table'] = leagueData

        print (f'{name}')
    
    return cups

async def getCupsList():
    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()

        # Open the URL
        await page.goto(baseIFAUrl)

        # Wait for the submenu to be visible
        submenu_locator = (await page.query_selector_all("ul.second-level-list"))[3]
        #submenu_locator = await page.wait_for_selector("ul.submenu")

        # Scan all submenu items
        cupsList = await scarpCupList(page, submenu_locator)

        #cupsList = helpers.load_from_json('./data/tournaments/cups.json')

        # Output the collected data
        for cup in cupsList:
            print(f"Text: {cup}, Link: {cupsList[cup]['href']}")

        # Close the browser
        await browser.close()

        helpers.save_to_file(cupsList, './data/tournaments/cups.json')

async def getLeaguesList():
    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()

        # Open the URL
        await page.goto(baseIFAUrl)

        # Wait for the submenu to be visible
        submenu_locator = (await page.query_selector_all("ul.second-level-list"))[2]
        #submenu_locator = await page.wait_for_selector("ul.submenu")

        # Scan all submenu items
        #await scarpLeaguesList(page, submenu_locator)
        await scrapLeaguesData(page)

        leaguesList = helpers.load_from_json('./data/tournaments/tournaments.json')

        # Output the collected data
        for league in leaguesList:
            print(f"Text: {league}, Link: {leaguesList[league]['href']}")

        # Close the browser
        await browser.close()

        helpers.save_to_json(leaguesList, './data/tournaments/tournaments.json')

async def fix_women_leagues(leagueSection, leagueText):
    sections = helpers.load_from_json('./data/tournaments/sections.json')
    if leagueSection == 'נשים':
        for section in sections:
            if section in leagueText:
                leagueSection = section

    return leagueSection

async def getLeagueName(page, tournamentUrl):
    if page.url != f'{baseIFAUrl}{tournamentUrl}':
        await page.goto(f'{baseIFAUrl}{tournamentUrl}')
    await scroll_to_bottom(page)
    tableTitle = await page.query_selector_all('span.big')
    if tableTitle and len(tableTitle) == 1: 
        return (await tableTitle[0].inner_text()).strip()
    return None

async def getVoleTableData(page):
    table_data = {}
    tableTitle = await page.query_selector_all('h1')
    if tableTitle: 
        div = await page.query_selector_all("div.tables_container__iVr6u")
        if not div:
            print(f"No element found with selector: {'div.vertical-title'}")
            return table_data

        headMapping = {
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
            for i in range(len(elements)):
                cell = elements[i]
                head = None
                if i == 0:
                    head = 'מיקום'
                else:
                    head = await theadTr[i-1].inner_text()
                
                obj = (await cell.inner_text()).strip()
                if headMapping.get(head):
                    head = headMapping[head]
                cells[head] = obj
            teamName = cells['קבוצה'].translate(translation_table)
            table_data[teamName] = cells

    return table_data

async def getIFATableData(page):
    table_data = {}
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
            teamName = cells['קבוצה'].translate(translation_table)
            table_data[teamName] = cells

    return table_data

async def scroll_to_bottom(page):
    try:
        for i in range(0, 10):
            await page.evaluate(f"""() => {{window.scrollTo(0, {i*20} );}}""")
            await asyncio.sleep(25/1000)
    except Exception as e:
        pass

async def getVoleLeagueData(page, voleUrl):
    table_data = {}
    t = 0
    while table_data == {} and t < 2:
        try:
            if page.url != f'{baseVoleUrl}{voleUrl}':
                await page.goto(f'{baseVoleUrl}{voleUrl}', timeout=10000)
            await page.wait_for_load_state(state='load', timeout=5000)
            await asyncio.sleep(50/1000)
            await scroll_to_bottom(page)
            table_data = await getVoleTableData(page)
        except Exception as e:
            pass
        finally:
            pass

        t = t + 1

    return table_data


async def getIFALeagueData(page, tournamentUrl):
    table_data = {}
    t = 0
    while table_data == {} and t < 2:
        try:
            if page.url != f'{baseIFAUrl}{tournamentUrl}':
                await page.goto(f'{baseIFAUrl}{tournamentUrl}', timeout=10000)
            await page.wait_for_load_state(state='load', timeout=5000)
            await asyncio.sleep(50/1000)
            await scroll_to_bottom(page)
            table_data = await getIFATableData(page)
        except Exception as e:
            pass
        finally:
            pass

        t = t + 1

    return table_data

async def updateLeagues():
    leagues = helpers.load_from_file('./data/tournaments/cups.json')
    for league in leagues:
        if leagues[league].get('tournament'):
            del leagues[league]['tournament']
        leagues[league]['tournament'] = 'cup'
    helpers.save_to_file(leagues, './data/tournaments/cups.json')

async def refreshLeagueTable(page, tournament, section):
    if tournament['tournament'] == 'cup':
        return
    #print(f"league={tournament} --> {section['tableResult']}")
    leagueTable = None
    if section['tableResult'] == 'IFA':
        leagueTable = await getIFALeagueData(page, tournament['href'])
    elif section['tableResult'] == 'Vole':
        if tournament.get('voleHref'):
            leagueTable = await getVoleLeagueData(page, tournament['voleHref'])
    if leagueTable or False:
        if tournament.get('table'):
            del tournament['table']
        print(f'league={tournament} rows={len(leagueTable)}')

        tableFilePath = f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tables/leagueId{tournament["leagueId"]}.json'
        if os.path.exists(tableFilePath):
            fileDateTime = datetime.fromtimestamp(os.path.getmtime(tableFilePath)).strftime("%Y%m%d%H%M%S")
            shutil.copy(tableFilePath,f'{tableFilePath}_{fileDateTime}' )
        helpers.save_to_file(leagueTable, tableFilePath)

async def refreshLeaguesTables(forceLoad = True, leagueName = None):
    sections = helpers.load_from_file(f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/sections.json')
    tournaments = helpers.load_from_file(f'{os.getenv("MY_DATA_FILE", f"/run/data/")}tournaments/tournaments.json')

    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        for tournamentName in tournaments:
            tournament = tournaments[tournamentName]
            if leagueName and leagueName != tournamentName:
                continue
            if sections.get(tournament.get('section')):
                await refreshLeagueTable(page, tournament, sections[tournament.get('section')])

        await browser.close()

    return True

async def getGameUrl(page, tournament, homeTeamId, guestTeamId, homeTeamName, guestTeamName):
    try:
        aRow = None
        divRow = None
        await page.goto(f"{baseIFAUrl}{tournament['href']}")        
        await scroll_to_bottom(page)
        
        if homeTeamId:
            selector = f".table_row[data-team1='{homeTeamId}'][data-team2='{guestTeamId}']"
            aRows = await page.query_selector_all(f"a{selector}")
            if aRows and len(aRows) == 1:
                aRow = aRows[0]

        else:
            div = page.locator(f"div.results-grid")

            # Ensure the div exists before continuing
            if await div.count() == 0:
                return None

            # Select all spans under divs with the class 'player'
            gamesRows = div.locator("a.table_row")
            games = [(gamesRows.nth(i)) for i in range(await gamesRows.count())]
            for game in games:
                gameText = await game.inner_text()
                if homeTeamName in gameText and guestTeamName in gameText:
                    aRow = game
                    break

        if aRow:
            return f'{baseIFAUrl}{await aRow.get_attribute("href")}'
    except Exception as e:
        print(f'Error in getGameUrl {e}')
    
    return None

async def scrapTeamSectionDetails(page, ariaAttributeValue, coach = False):
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

def parsePlayersSpans(playersSpans):
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

def formatPlayers(players):
    sortedPlayers = dict(sorted(players.items(), key=lambda player: player[1]['no']))
    formatedPlayers =  [f"{'ק' if sortedPlayers[playerNo].get('c') else ''}{'ש' if sortedPlayers[playerNo].get('gk') else ''}{sortedPlayers[playerNo]['no']}" for playerNo in sortedPlayers]
    return formatedPlayers

async def scrapGameDetails(page, url):
    # Navigate to the URL
    await page.goto(url)

    homeActiveSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_ACTIVE_HOME')
    homeReplacementSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Replacement_HOME')
    homeBenchSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Bench_HOME')
    homeCoachSpans = await scrapTeamSectionDetails(page, 'GAME_COACH_HOME', True)
    awayActiveSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_ACTIVE_GUEST')
    awayReplacementSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Replacement_GUEST')
    awayBenchSpans = await scrapTeamSectionDetails(page, 'GAME_PLAYER_TYPE_Bench_GUEST')
    awayCoachSpans = await scrapTeamSectionDetails(page, 'GAME_COACH_GUEST', True)

    homeActivePlayers = parsePlayersSpans(homeActiveSpans)
    homeReplacementPlayers = parsePlayersSpans(homeReplacementSpans)
    homeBenchPlayers = parsePlayersSpans(homeBenchSpans)
    homeCoach = homeCoachSpans[1] if homeCoachSpans else ''
    awayActivePlayers = parsePlayersSpans(awayActiveSpans)
    awayReplacementPlayers = parsePlayersSpans(awayReplacementSpans)
    awayBenchPlayers = parsePlayersSpans(awayBenchSpans)
    awayCoach = awayCoachSpans[1] if awayCoachSpans else ''

    formatedHomeActivePlayers = formatPlayers(homeActivePlayers)
    formatedHomeReplacementPlayers = formatPlayers(homeReplacementPlayers)
    formatedHomeBenchPlayers = formatPlayers(homeBenchPlayers)
    formatedAwayActivePlayers = formatPlayers(awayActivePlayers)
    formatedAwayReplacementPlayers = formatPlayers(awayReplacementPlayers)
    formatedAwayBenchPlayers = formatPlayers(awayBenchPlayers)

    return formatedHomeActivePlayers, formatedHomeReplacementPlayers, formatedHomeBenchPlayers, homeCoach, \
        formatedAwayActivePlayers, formatedAwayReplacementPlayers, formatedAwayBenchPlayers, awayCoach

async def createSections():
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

async def askToApproveGame(game):
    game['askToApproveGame'] = True

async def approveGame(self, page, refId, gameId):
    pass

async def openBrowser():
    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        players = await scrapGameDetails(page, 'https://vole.one.co.il')
        await scrapVoleLeagues(page)
        pass
        #asyncio.run(refreshLeaguesTables())

        homeActiveNos = ','.join(players[0])
        homeReserveNos = ','.join(players[1])
        homeCoach = players[3]
        awayActiveNos = ','.join(players[4])
        awayReserveNos = ','.join(players[5])
        awayCoach = players[7]
        message = f'\nלהלן הקישור לפרטי המשחק'
        message += '\n*קבוצה ביתית:*'
        message += f'\n*הרכב:* {homeActiveNos}'
        message += f'\n*ספסל:* {homeReserveNos}'
        message += '\n*קבוצה אורחת:*'
        message += f'\n*הרכב:* {awayActiveNos}'
        message += f'\n*ספסל:* {awayReserveNos}'

        browser.close

if __name__ == "__main__":
    asyncio.run(refreshLeaguesTables())
    #asyncio.run(openBrowser())

    pass
