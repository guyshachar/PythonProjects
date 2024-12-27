from playwright.async_api import async_playwright
import asyncio
import helpers
from urllib.parse import urlparse, parse_qs

baseUrl = "https://www.football.org.il"

# Function to extract submenu items
async def scarpLeaguesList(page, submenu_locator):
    sections = helpers.load_from_json('./data/leagues/sections.json')
    submenu_items = await submenu_locator.query_selector_all("li")
    leaguesList = []
    leagues = {}
    leagueSection = None
    for item in submenu_items:
        text = (await item.inner_text()).strip()
        link = await item.query_selector("a")
        href = await link.get_attribute("href") if link else None
        query = urlparse(href).query
        params = parse_qs(query)
        leagueId = int(params.get('league_id', 0)[0])
        name = text
        if leagueId == 0:
            leagueSection = text[:text.find('\n')]
            leagueSection = await fix_women_leagues(leagueSection, text)
        else:
            leaguesList.append({ 'text': text, 'section': leagueSection, 'leagueId': leagueId, 'href': href, 'table' : {}})

    for league in leaguesList:
        name = await getLeagueName(page, league['href'])
        leagueData = await getLeagueData(page, league['href'])
        leagues[name] = league
        if sections[league['section']]['tableResult'] == True:
            leagues[name]['table'] = leagueData

        print (f'{name} => {len(leagueData)}')
    
    return leagues

async def scrapLeaguesData(page):
    leaguesList = helpers.load_from_json('./data/leagues/leagues.json')
    sections = helpers.load_from_json('./data/leagues/sections.json')

    for league in leaguesList:
        leagueData = await getLeagueData(page, leaguesList[league]['href'])
        if sections[leaguesList[league]['section']]['tableResult'] == True:
            leaguesList[league]['table'] = leagueData

        print (f'{league} => {len(leagueData)}')

    helpers.save_to_json(leaguesList, './data/leagues/leagues.json')

async def getLeaguesList():
    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        page = await browser.new_page()

        # Open the URL
        await page.goto(baseUrl)

        # Wait for the submenu to be visible
        submenu_locator = (await page.query_selector_all("ul.second-level-list"))[2]
        #submenu_locator = await page.wait_for_selector("ul.submenu")

        # Scan all submenu items
        #await scarpLeaguesList(page, submenu_locator)
        await scrapLeaguesData(page)

        leaguesList = helpers.load_from_json('./data/leagues/leagues.json')

        # Output the collected data
        for league in leaguesList:
            print(f"Text: {league}, Link: {leaguesList[league]['href']}")

        # Close the browser
        await browser.close()

        helpers.save_to_json(leaguesList, './data/leagues/leagues.json')

async def fix_women_leagues(leagueSection, leagueText):
    sections = helpers.load_from_json('./data/leagues/sections.json')
    if leagueSection == 'נשים':
        for section in sections:
            if section in leagueText:
                leagueSection = section

    return leagueSection

async def getLeagueName(page, leagueUrl):
    if page.url != f'{baseUrl}{leagueUrl}':
        await page.goto(f'{baseUrl}{leagueUrl}')
    await scroll_to_bottom(page)
    tableTitle = await page.query_selector_all('span.big')
    if tableTitle and len(tableTitle) == 1: 
        return (await tableTitle[0].inner_text()).strip()
    return None

async def getTableData(page):
    table_data = {}
    tableTitle = await page.query_selector_all('h2#LEAGUE_TABLE_TITLE_PLAYOFF')
    if tableTitle: 
        full_view_div = await page.query_selector_all("div.vertical-title")
        if not full_view_div:
            print(f"No element found with selector: {"div.vertical-title"}")
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
            table_data[cells['קבוצה']] = cells

    return table_data

async def scroll_to_bottom(page):
    for i in range(0, 10):
        await page.evaluate(f"""() => {{window.scrollTo(0, {i*20} );}}""")
        await asyncio.sleep(50/1000)

async def getLeagueData(page, leagueUrl):
        table_data = {}
        t = 0
        while table_data == {} and t < 2:
            try:
                if page.url != f'{baseUrl}{leagueUrl}':
                    await page.goto(f'{baseUrl}{leagueUrl}', timeout=10000)
                await page.wait_for_load_state(state='load', timeout=5000)
                await asyncio.sleep(50/1000)
                await scroll_to_bottom(page)
                table_data = await getTableData(page)
            except Exception as e:
                pass
            finally:
                pass

            t = t + 1

        return table_data

async def getLeaguesData(forceLoad = True):
    sections = helpers.load_from_json('./data/leagues/sections.json')
    leagues = helpers.load_from_json('./data/leagues/leagues.json')

    async with async_playwright() as p:                
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        for league in leagues:
            leagueTable = leagues[league]['table']
            if leagues[league]['section'] in sections and sections[leagues[league]['section']]['tableResult'] == True and (not leagueTable or forceLoad == True):
                print(f'league={league} -->')
                leagueName, leagueTable = await getLeagueData(page, leagues[league]['href'])
                if leagueTable or False:
                    leagues[league]['table'] = leagueTable
                    print(f'league={league} rows={len(leagueTable)}')

        await browser.close()

        helpers.save_to_json(leagues, './data/leagues/leagues.json')

async def getGameUrl(page, league, homeTeam, awayTeam):
    try:
        aRow = None
        divRow = None
        await page.goto(f'{baseUrl}{league['href']}')        
        await scroll_to_bottom(page)
        await page.wait_for_selector(f"div[class='table_row']")
        
        if not isinstance(homeTeam, str):
            selector = f'.table_row[data-team1="{homeTeam['teamId']}"][data-team2="{awayTeam['teamId']}"]'
            aRows = await page.query_selector_all(f"a{selector}")
            if aRows and len(aRows) == 1:
                aRow = aRows[0]
            divRow = await page.query_selector_all(f"div{selector}")

        if not aRow:
            rows = await page.query_selector_all(f'a.table_row')
            for row in rows:
                rowText = await row.inner_text()
                if homeTeam in rowText:
                    aRow = row
                    break

        if aRow:
            return f'{baseUrl}{await aRow.get_attribute("href")}'
        elif divRow:
            return None
    except Exception as e:
        print(f'Error in getGameUrl {e}')
    
    return None

async def createSections():
    leagues = helpers.load_from_json('./data/leagues/leagues.json')
    sections = {}
    for league in leagues:
        section = league['section']
        if section not in sections:
            sections[section] = { "tableResult": False}
            continue

    helpers.save_to_json(sections, './data/leagues/sections.json')

if __name__ == "__main__":
    pass
    leagues = asyncio.run(getLeaguesList())