from playwright.async_api import async_playwright
import asyncio
from urllib.parse import urlparse, parse_qs
import os
import sys
import logging
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
        leagueVoleUrl = await leagueRow.get_attribute('href')
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
        await helpers.gotoUrl(page, baseIFAUrl)

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
        await helpers.gotoUrl(page, baseIFAUrl)

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
        await helpers.gotoUrl(page, f'{baseIFAUrl}{tournamentUrl}', timeout=15000)
    tableTitle = await page.query_selector_all('span.big')
    if tableTitle and len(tableTitle) == 1: 
        return (await tableTitle[0].inner_text()).strip()
    return None

async def getVoleTableData(page):
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
            teamName = cells['קבוצה'].translate(translation_table)
            table_data[teamName] = cells

    return table_data

async def getIFATableData(page):
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
                    teamName = cells['קבוצה'].translate(translation_table)
                    table_data[teamName] = cells

    return table_data

async def getVoleLeagueData(page, voleUrl):
    table_data = {}
    t = 0
    while table_data == {} and t < 2:
        try:
            if page.url != f'{baseVoleUrl}{voleUrl}':
                await helpers.gotoUrl(page, f'{baseVoleUrl}{voleUrl}', timeout=15000)
            await asyncio.sleep(50/1000)
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
                await helpers.gotoUrl(page, f'{baseIFAUrl}{tournamentUrl}', timeout=15000)
            await asyncio.sleep(50/1000)
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
                await refreshLeagueTable(page, tournament, sections[tournament.get('section')])

        await browser.close()

    return found

async def getGameUrl(page, tournament, round, fixture, homeTeamId, guestTeamId, homeTeamName, guestTeamName):
    try:
        aRow = None
        url = f"{baseIFAUrl}{tournament['href']}"
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
            logging.info(f'המשחק {homeTeamName} נגד {guestTeamName} פורסם')
            return f'{baseIFAUrl}{await aRow.get_attribute("href")}'
        
    except Exception as ex:
        logging.error(f'Error in getGameUrl {url} {ex}')
    
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
    #formatedPlayers =  [f"{'ק' if sortedPlayers[playerNo].get('c') else ''}{'ש' if sortedPlayers[playerNo].get('gk') else ''}{sortedPlayers[playerNo]['no']}" for playerNo in sortedPlayers]
    captainPlayer = next((key for key, value in players.items() if value.get('c') == True), None)
    goalkeeperPlayer = next((key for key, value in players.items() if value.get('gk') == True), None)
    formatedPlayers = []
    if captainPlayer:
        formatedPlayers.append(str(captainPlayer))
    if goalkeeperPlayer:
        formatedPlayers.append(str(goalkeeperPlayer))
    formatedPlayers += [f"{sortedPlayers[playerNo]['no']}" for playerNo in sortedPlayers  if (not captainPlayer or playerNo != captainPlayer) and (not goalkeeperPlayer or playerNo != goalkeeperPlayer)]
    return formatedPlayers

async def scrapGameDetails(page, url):
    # Navigate to the URL
    await helpers.gotoUrl(page, url)

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

async def approveGame(refereeDetail, gameId, statusCell, page):
    try:
        logging.info(f'approveGame refId={refereeDetail["refId"]} gameId={gameId} title={page.url}')
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
        logging.error(f'approveGame error: {ex}')

async def openBrowser():
    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()
        #await page.goto
        #textLocator = page.locator('div.table_data_header')
        #await textLocator.inner_text()
        players = await scrapGameDetails(page, 'https://www.football.org.il/leagues/games/game/?game_id=972746')
        #await scrapVoleLeagues(page)
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
    #asyncio.run(refreshLeaguesTables())
    asyncio.run(openBrowser())

    pass
