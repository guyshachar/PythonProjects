#!/usr/bin/env python3
"""
Handball Assignment Parser with Playwright
Navigates to URL and parses all assignments with pagination
"""

import asyncio
import json
import csv
import re
import logging
import sys
from playwright_stealth import Stealth
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import shared.helpers as helpers
import shared.jsonHelper as jsonHelper
from logging import Logger

# Playwright imports
try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Playwright not installed. Please install with: pip install playwright")

@dataclass
class Referee:
    """Represents a referee with ID and name"""
    id: str
    name: str

@dataclass
class Game:
    """Represents a handball game with all its details"""
    internalGameId: str
    date: datetime
    homeTeam: str
    guestTeam: str
    field: str
    tournamentName: str
    fixture: str
    referees: List[dict]  # Type1, Type2, etc.
    result_approved: bool
    additional_assignments_available: bool
    page_number: int = 1
    table_type: str = "handball_assignments"

class IHAParser:
    """Parser for handball assignments with Playwright support"""
    
    def __init__(self, logger:Logger, headless: bool = True, timeout: int = 30000, page: Page = None):
        self.logger = logger
        self.headless = headless
        self.timeout = timeout
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pageInitialized = True if page else False
        self.page: Optional[Page] = page
        self.playwright = None
        self.games: List[Game] = []
        self.all_referees: List[Referee] = []
    
    async def __aenter__(self):
        """Async context manager entry"""
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("Playwright is not installed. Please install it with: pip install playwright")
        if not self.pageInitialized:
            await self.start_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        
        if not self.pageInitialized:
            await self.close_browser()
    
    async def start_browser(self):
        if not self.pageInitialized:
            """Start Playwright browser"""
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-dev-shm-usage']
            )
            self.context = await self.createContext(browser=self.browser)
            stealth = Stealth()
            await stealth.apply_stealth_async(self.context)
            self.page = await self.context.new_page()
            await self.page.set_default_timeout(self.timeout)
    
    async def close_browser(self):
        """Close Playwright browser"""
        if self.pageInitialized:
            return

        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def parse_url_with_pagination(self, url: str, max_pages: int = 10) -> List[Game]:
        """Parse a URL with pagination support"""
        if not await self.navigate_to_url(url):
            return []
        
        all_games = []
        page_number = 1
        empty_pages = 0
        while page_number <= max_pages:
            self.logger.info(f"Parsing page {page_number}...")
            
            # Wait for the form and table to load
            try:
                await self.page.wait_for_selector('form[name="Assign"]', timeout=10000)
                await self.page.wait_for_selector('table.devices', timeout=10000)
            except Exception as e:
                self.logger.debug(f"Form or table not found on page {page_number}:", e)
                break
            
            # Parse current page
            page_games = await self.parse_current_page(page_number)
            all_games.extend(page_games)
            self.logger.info(f"Found {len(page_games)} games on page {page_number}")
            assignedGames = any([game for game in page_games if game.referees])
            if not assignedGames:
                empty_pages += 1
                self.logger.warning(f"No assigned games found on page {page_number}")
                if empty_pages > 1:
                    self.logger.warning(f"No assigned games found on {empty_pages} pages, stopping parsing")
                    break
            else:
                empty_pages = 0

            # Try to find and click next page button
            next_page_clicked = await self.click_next_page()
            if not next_page_clicked:
                self.logger.debug("No more pages available")
                break
            
            page_number += 1
            # Wait a bit between pages
            await asyncio.sleep(2)
        
        self.games = all_games
        return all_games
    
    async def navigate_to_url(self, url: str) -> bool:
        """Navigate to the target URL"""
        try:
            self.logger.debug(f"Navigating to: {url}")
            await self.page.goto(url, wait_until='networkidle', timeout=60000)
            await self.page.wait_for_load_state('domcontentloaded')
            return True
        except Exception as e:
            self.logger.debug(f"Error navigating to URL:", e)
            return False
    
    async def parse_current_page(self, page_number: int) -> List[Game]:
        """Parse the current page for game data"""
        try:
            # Get page content
            content = await self.page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            # Extract all referees from the first dropdown (only on first page)
            if page_number == 1:
                self.all_referees = self._extract_all_select_options(soup, select_name=re.compile(r'Type1_\d+'))
                jsonHelper.save_to_file(self.all_referees, f'./all_handball_referees.json')
                self.all_arenas = self._extract_all_select_options(soup, select_name='ArenaId')
                jsonHelper.save_to_file(self.all_arenas, f'./all_handball_arenas.json')
                self.all_tournaments = self._extract_all_select_options(soup, select_name='CompId')
                jsonHelper.save_to_file(self.all_tournaments, f'./all_handball_tournaments.json')

            # Find the form with name="Assign"
            form = soup.find('form', {'name': 'Assign'})
            if not form:
                self.logger.debug("Form with name 'Assign' not found")
                return []
            
            # Find the table within the form
            table = form.find('table', class_='devices')
            if not table:
                self.logger.debug("Table with class 'devices' not found in form")
                return []
            
            rows = table.find_all('tr')

            # Find all game rows
            game_rows = self._find_game_rows(rows=rows)
            games = []
            
            for row in rows:
                game = self._parse_game_row(row=row, page_number=page_number)
                if game:
                    games.append(game)
            
            return games
            
        except Exception as e:
            self.logger.debug(f"Error parsing page {page_number}:", e)
            return []
    
    async def click_next_page(self) -> bool:
        """Click the next page button using img alt='עמוד הבא'"""
        try:
            # Look for the next page button with alt text 'עמוד הבא'
            next_button = await self.page.query_selector('a.nav_next_a')
            
            if next_button:
                self.logger.debug("Clicking next page button...")
                await next_button.click()
                await self.page.wait_for_load_state('networkidle')
                await asyncio.sleep(2)  # Wait for page to load
                return True
            else:
                self.logger.debug("Next page button not found")
                return False
                
        except Exception as e:
            self.logger.debug(f"Error clicking next page:", e)
            return False
    
    def _extract_all_select_options(self, soup: BeautifulSoup, select_name: str) -> dict:
        """Extract all available referees from the first dropdown"""
        # Find the first Type1 dropdown
        options = {}
        first_select = soup.find('select', {'name': select_name})
        if first_select:
            for option in first_select.find_all('option'):
                if option.get('value') == '0':  # Skip the default "-" option
                    continue
                
                value = option.get('value', '')
                text = option.get_text(strip=True).replace('\xa0', ' ')
                
                # Avoid duplicates
                if not any(optionValue == value for optionValue in options.keys()):
                    options[value] = text
        return options

    def _find_game_rows(self, rows) -> List:
        """Find all game data rows"""
        game_rows = []
        
        for row in rows:
            # Skip header row
            if row.find('th') or 'header' in str(row.get('class', [])):
                continue
            
            # Skip update button row
            if 'עדכן' in str(row) or 'update' in str(row).lower():
                continue
            
            # Check if this row has game data
            game_link = row.find('a', href=lambda x: x and 'GameId=' in x)
            if game_link:
                game_rows.append(row)
        
        return game_rows
    
    def _parse_game_row(self, row, page_number: int) -> Optional[Game]:
        """Parse a single game row and extract all information"""
        try:
            cells = row.find_all('td')
            if len(cells) < 13:
                return None
            
            # Extract game ID
            game_id_link = cells[-1].find('a', href=lambda x: x and 'GameId=' in x)
            if not game_id_link:
                return None
            
            internal_game_id = game_id_link.get_text(strip=True)
            
            # Extract date and time
            date_time_cell = cells[-2]
            date_time_text = date_time_cell.get_text(strip=True)
            date_match = re.search(r'(\d{2}/\d{2}/\d{4})', date_time_text)
            time_match = re.search(r'(\d{2}:\d{2})', date_time_text)
            
            date = date_match.group(1) if date_match else ''
            time = time_match.group(1) if time_match else ''
            
            # Extract teams
            home_team = cells[-6].get_text(strip=True)
            away_team = cells[-7].get_text(strip=True)
            
            # Extract venue and league
            venue = cells[-3].get_text(strip=True)
            league = cells[-4].get_text(strip=True)
            fixture = cells[-5].get_text(strip=True)
            
            # Extract referee assignments
            referees = self._extract_referee_assignments(row=row, game_id=internal_game_id)
            
            # Check if result is approved
            result_approved = 'nav-stop.png' in str(row)
            
            # Check if additional assignments are available
            additional_assignments = 'update.png' in str(row)
            
            return Game(
                internalGameId=internal_game_id,
                date=helpers.convert_to_datetime(f'{date}T{time}'),
                homeTeam=home_team,
                guestTeam=away_team,
                field=venue,
                tournamentName=league,
                fixture=fixture,
                referees=referees,
                result_approved=result_approved,
                additional_assignments_available=additional_assignments,
                page_number=page_number,
                table_type="handball_assignments"
            )
            
        except Exception as ex:
            self.logger.error(f"Error parsing game row:", ex)
            return None
    
    def _extract_referee_assignments(self, row, game_id: str) -> list:
        """Extract referee assignments from the row"""
        refereeRoles = {
            1: 'שופט',
            2: 'שופט',
            3: 'מבקר',
            4: 'מזכיר',
            5: 'מזכיר'
        }
        statusColors = {
            '#c9ffa9': 'שיבוץ אושר',
            '#dfdfdf': 'שיבוץ מחכה לאישור',
            '#ffa8a8': 'שיבוץ נדחה',
            'yellowgreen': 'לא זמין'
        }
        
        assignments = []
        
        # Look for Type1_GameId, Type2_GameId, etc.
        for i in range(1, 6):
            select_name = f"Type{i}_{game_id}"
            select_element = row.find('select', {'name': select_name})
            if select_element:
                selected_option = select_element.find('option', selected=True)
                if not selected_option:
                    continue
                role = refereeRoles.get(i, '')
                refId = selected_option.get('value')
                refName = selected_option.get_text(strip=True)
                bgColor = select_element.get('style', '').split('background-color:')[1].split(';')[0]
                if selected_option and refId != '0':
                    assignments.append({
                        'role': role,
                        'refId': refId,
                        'refName': refName.replace('\xa0', ' '),
                        'status': statusColors.get(bgColor, 'notAssigned')
                    })
                elif False:
                    pass
            elif False:
                pass
        
        return assignments
    
    async def to_json(self, filename: Optional[str] = None) -> str:
        """Convert games to JSON format"""
        games_data = []
        for game in self.games:
            game_dict = asdict(game)
            games_data.append(game_dict)
        
        jsonHelper.save_to_file(games_data, filename)
    
    async def to_csv(self, filename: str):
        """Export games to CSV format"""
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'game_id', 'date', 'time', 'home_team', 'away_team', 
                'venue', 'league', 'fixture', 'referees',
                'result_approved', 'additional_assignments_available', 
                'page_number', 'table_type'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for game in self.games:
                row = {
                    'game_id': game.internalGameId,
                    'date': game.date,
                    'home_team': game.homeTeam,
                    'away_team': game.guestTeam,
                    'venue': game.field,
                    'league': game.tournamentName,
                    'fixture': game.fixture,
                    'referees': game.referees,
                    'result_approved': game.result_approved,
                    'additional_assignments_available': game.additional_assignments_available,
                    'page_number': game.page_number,
                    'table_type': game.table_type
                }
                writer.writerow(row)
    
    async def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the parsed data"""
        total_games = len(self.games)
        total_referees = len(self.all_referees)
        approved_results = sum(1 for game in self.games if game.result_approved)
        
        # Get unique venues and leagues
        venues = list(set(game.field for game in self.games))
        leagues = list(set(game.tournamentName for game in self.games))
        
        # Get page distribution
        page_distribution = {}
        for game in self.games:
            page_num = game.page_number
            page_distribution[page_num] = page_distribution.get(page_num, 0) + 1
        
        return {
            'total_games': total_games,
            'total_referees': total_referees,
            'approved_results': approved_results,
            'unique_venues': venues,
            'unique_leagues': leagues,
            'page_distribution': page_distribution,
            'date_range': {
                'earliest': min(game.date for game in self.games) if self.games else None,
                'latest': max(game.date for game in self.games) if self.games else None
            }
        }


async def main():
    """Main function to run the assignment parser"""
    logger = logging.getLogger(__name__)
    if not PLAYWRIGHT_AVAILABLE:
        logger.debug("❌ Playwright is not installed!")
        logger.debug("Please install it with: pip install playwright")
        logger.debug("Then run: playwright install chromium")
        return
    
    # Configuration
    url = input("Enter the URL to parse: ").strip()
    if not url:
        logger.debug("No URL provided. Exiting.")
        return
    
    max_pages = input("Enter maximum pages to parse (default 10): ").strip()
    max_pages = int(max_pages) if max_pages.isdigit() else 10
    
    headless_choice = input("Run in headless mode? (y/n, default: y): ").strip().lower()
    headless = headless_choice != 'n'
    
    logger.debug("\n" + "="*60)
    logger.debug("HANDBALL ASSIGNMENT PARSER")
    logger.debug("="*60)
    logger.debug(f"Target URL: {url}")
    logger.debug(f"Max pages: {max_pages}")
    logger.debug(f"Headless mode: {headless}")
    logger.debug("-"*60)
    
    async with IHAParser(logger=logging.getLogger(__name__), headless=headless) as parser:
        try:
            summary = await parser.get_summary()
            logger.info(f"\n📊 SUMMARY:")
            logger.debug(f"  Total games: {summary['total_games']}")
            logger.debug(f"  Total referees: {summary['total_referees']}")
            logger.debug(f"  Approved results: {summary['approved_results']}")
            logger.debug(f"  Unique venues: {len(summary['unique_venues'])}")
            logger.debug(f"  Unique leagues: {len(summary['unique_leagues'])}")
            
            # Show page distribution
            if summary['page_distribution']:
                logger.debug(f"\n📄 PAGE DISTRIBUTION:")
                for page_num, count in sorted(summary['page_distribution'].items()):
                    logger.debug(f"  Page {page_num}: {count} games")
            
            # Export data
            logger.debug(f"\n💾 EXPORTING DATA:")
            logger.debug("  Exporting to JSON...")
            await parser.to_json('handball_assignments.json')
            logger.debug("  ✅ JSON exported to 'handball_assignments.json'")
            
            logger.debug("  Exporting to CSV...")
            await parser.to_csv('handball_assignments.csv')
            logger.debug("  ✅ CSV exported to 'handball_assignments.csv'")
            
            # Show sample games
            logger.debug(f"\n🎮 SAMPLE GAMES:")
            games = parser.games
            for i, game in enumerate(games[:3], 1):  # Show first 3 games
                logger.debug(f"\n  Game {i} (Page {game.page_number}):")
                logger.debug(f"    ID: {game.game_id}")
                logger.debug(f"    Date/Time: {game.date} at {game.time}")
                logger.debug(f"    Match: {game.home_team} vs {game.away_team}")
                logger.debug(f"    Venue: {game.venue}")
                referees = [ref for ref in game.referees.values() if ref]
                if referees:
                    logger.debug(f"    Referees: {', '.join(referees)}")
                else:
                    logger.debug(f"    Referees: None assigned")
            
            if len(games) > 3:
                logger.debug(f"  ... and {len(games) - 3} more games")
            
            logger.debug(f"\n" + "="*60)
            logger.debug("PARSING COMPLETE!")
            logger.debug("="*60)
            
        except Exception as e:
            logger.debug(f"❌ Error during parsing:", e)
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    print("Handball Assignment Parser with Playwright")
    print("Parses assignments from form[name='Assign'] with pagination")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nParsing interrupted by user.")
    except Exception as e:
        print(f"\nUnexpected error:", e)
        import traceback
        traceback.print_exc()