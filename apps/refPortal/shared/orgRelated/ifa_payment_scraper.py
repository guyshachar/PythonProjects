#!/usr/bin/env python3
"""
Payment Records Scraper using Playwright
Scrapes all payments records from a table and navigates through pages using pagination.
"""

import asyncio
import json
import csv
from datetime import datetime
from pathlib import Path
import sys
from playwright.async_api import async_playwright
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class IfaPaymentScraper:
    def __init__(self, logger:Logger):
        self.logger = logger

    async def extract_header_labels(self, page):
        """Extract header labels from the header row."""
        try:
            # Look for header row under thead under table
            header_row = await page.query_selector("table > thead > tr")
            
            if header_row:
                # Extract text from all cells in the header row
                header_cells = await header_row.query_selector_all("td, th")
                header_labels = []
                
                for cell in header_cells:
                    cell_text = await cell.text_content()
                    if cell_text and cell_text.strip():
                        header_labels.append(cell_text.strip())
                
                self.logger.info(f"Extracted header labels: {header_labels}")
                return header_labels
            else:
                self.logger.warning("Header row with class '_ngcontent-cyb-c202' not found")
                return None
                
        except Exception as ex:
            self.logger.warning(f"Error extracting header labels:", ex)
            return None

    async def get_current_season(self, page):
        """Extract current season from seasonDropDown select element."""
        try:
            # Look for select element with name="seasonDropDown"
            season_select = await page.query_selector("select[name='seasonDropDown']")
            
            if season_select:
                # Get the currently selected option
                selected_option = await season_select.query_selector("option:checked")
                if selected_option:
                    season_text = await selected_option.text_content()
                    if season_text and season_text.strip():
                        self.logger.info(f"Current season: {season_text.strip()}")
                        return season_text.strip()
                
                # If no selected option found, get the first option
                first_option = await season_select.query_selector("option")
                if first_option:
                    season_text = await first_option.text_content()
                    if season_text and season_text.strip():
                        self.logger.info(f"Using first season option: {season_text.strip()}")
                        return season_text.strip()
            
            self.logger.warning("Season dropdown not found or no options available")
            return "Unknown Season"
            
        except Exception as ex:
            self.logger.warning(f"Error extracting current season:", ex)
            return "Unknown Season"

    async def get_all_seasons(self, page):
        """Get all available seasons from seasonDropDown select element."""
        try:
            # Look for select element with name="seasonDropDown"
            season_select = await page.query_selector("select[name='seasonDropDown']")
            
            if season_select:
                # Get all option elements
                options = await season_select.query_selector_all("option")
                seasons = []
                
                for option in options:
                    season_text = await option.text_content()
                    if season_text and season_text.strip():
                        seasons.append(season_text.strip())
                
                self.logger.info(f"Found {len(seasons)} seasons: {seasons}")
                return seasons
            
            self.logger.warning("Season dropdown not found")
            return []
            
        except Exception as ex:
            self.logger.warning(f"Error extracting all seasons:", ex)
            return []

    async def select_season(self, page, season_name):
        """Select a specific season from the seasonDropDown select element."""
        try:
            # Look for select element with name="seasonDropDown"
            season_select = await page.query_selector("select[name='seasonDropDown']")
            
            if season_select:
                # Try to select the season by visible text
                await season_select.select_option(label=season_name)
                self.logger.info(f"Selected season: {season_name}")
                
                # Wait for the page to update after selection
                await page.wait_for_timeout(1000)
                return True
            else:
                self.logger.warning("Season dropdown not found")
                return False
                
        except Exception as ex:
            self.logger.warning(f"Error selecting season '{season_name}':", ex)
            return False

    async def reset_to_first_page(self, page):
        """Reset pagination to the first page for a new season."""
        try:
            while True:                
                prev_button = await page.query_selector_all("button[class*='arr-right'], .arr-right")
                if prev_button is None or await prev_button[0].is_disabled():
                    break

                await prev_button[0].click()
                await page.wait_for_timeout(500)

        except Exception as ex:
            self.logger.warning(f"Error resetting to first page:", ex)
            return False

    async def extract_payments_from_current_page(self, page):
        """Extract payments data from the current page."""
        try:
            header_labels = await self.extract_header_labels(page=page)

            # Extract current season from seasonDropDown
            current_season = await self.get_current_season(page)

            # Find all rows in the table
            rows = await page.query_selector_all("table.ng-star-inserted tr.ng-star-inserted")
            self.logger.info(f"Found {len(rows)} rows in the table")
            
            page_payments = []
            
            for i, row in enumerate(rows):
                try:
                    # Extract text from all cells in the row
                    cells = await row.query_selector_all("td")
                    if not cells:
                        continue
                    
                    # Create a dictionary for this payment record
                    payment_record = {
                        'row_number': i + 1,
                        'page_number': await self.get_current_page_number(page=page),
                        'timestamp': datetime.now().isoformat(),
                        'season': current_season,
                        'data': {}
                    }
                    
                    # Extract data from each cell
                    for j, cell in enumerate(cells):
                        cell_text = await cell.text_content()
                        if cell_text and cell_text.strip():
                            payment_record['data'][header_labels[j]] = cell_text.strip()
                    
                    # Also try to extract specific elements if they exist
                    try:
                        # Look for specific elements that might contain payment data
                        amount_elements = await row.query_selector_all("[class*='amount'], [class*='price'], [class*='total']")
                        for elem in amount_elements:
                            text = await elem.text_content()
                            if text and text.strip():
                                payment_record['data']['amount'] = text.strip()
                        
                        # Look for date elements
                        date_elements = await row.query_selector_all("[class*='date'], [class*='time']")
                        for elem in date_elements:
                            text = await elem.text_content()
                            if text and text.strip():
                                payment_record['data']['date'] = text.strip()
                        
                        # Look for status elements
                        status_elements = await row.query_selector_all("[class*='status'], [class*='state']")
                        for elem in status_elements:
                            text = await elem.text_content()
                            if text and text.strip():
                                payment_record['data']['status'] = text.strip()
                        
                    except Exception as ex:
                        self.logger.warning(f"Error extracting specific elements from row {i+1}:", ex)
                    
                    if payment_record['data']:
                        page_payments.append(payment_record)
                        self.logger.info(f"Extracted payment record {len(page_payments)} from row {i+1}")
                
                except Exception as ex:
                    self.logger.warning(f"Error processing row {i+1}:", ex)
                    continue
            
            self.logger.info(f"Successfully extracted {len(page_payments)} payment records from current page")
            return page_payments
            
        except Exception as ex:
            self.logger.error(f"Error extracting payments from current page:", ex)
            return []
    
    async def get_current_page_number(self, page):
        """Get the current page number from pagination."""
        try:
            # Look for pagination elements that might contain page numbers
            page_elements = await page.query_selector_all(
                "[class*='page'], [class*='pagination'], [class*='current'], [class*='active']"
            )
            
            for elem in page_elements:
                text = await elem.text_content()
                if text and text.strip().isdigit():
                    return int(text.strip())
            
            # If no page number found, return 1
            return 1
            
        except Exception as e:
            self.logger.warning(f"Could not determine current page number:", e)
            return 1
    
    async def click_next_page(self, page):
        """Click the 'arr-left' button to go to the next page."""
        try:
            # Look for the previous page button (arr-left)
            next_button = await page.query_selector_all("button[class*='arr-left'], .arr-left")
            
            if next_button and not await next_button[0].is_disabled():
                # Click the button
                await next_button[0].click()
                self.logger.info("Clicked next page button")
                
                # Wait for page to load
                await page.wait_for_timeout(500)
                                
                return True
            else:
                self.logger.warning("Next page button not found")
                return False
            
        except Exception as ex:
            self.logger.warning(f"Next page button not found or not clickable:", ex)
            return False
    
    async def scrape_all_pages(self, page, max_pages=50):
        """Scrape all pages of payments data for all seasons."""
        self.logger.info(f"Starting to scrape payments data for all seasons (max {max_pages} pages per season)")
        
        self.payments_data = []

        # Get all available seasons
        all_seasons = await self.get_all_seasons(page)
        if not all_seasons:
            self.logger.warning("No seasons found, scraping current season only")
            all_seasons = ["Current Season"]
        
        total_payments = 0
        total_seasons_processed = 0
        
        for season in all_seasons:
            self.logger.info(f"Processing season: {season}")
            
            # Select the season in the dropdown
            await self.select_season(page, season)
            
            # Wait for page to load after season selection
            await page.wait_for_timeout(500)
            
            # Reset to first page for this season
            await self.reset_to_first_page(page)
            
            # Scrape all pages for this season
            season_payments = await self.scrape_season_pages(page, max_pages)
            
            total_payments += season_payments
            total_seasons_processed += 1
            
            self.logger.info(f"Season '{season}' completed: {season_payments} payments extracted")
            
            # Small delay between seasons
            await page.wait_for_timeout(1000)
        
        self.logger.info(f"Scraping completed. Seasons processed: {total_seasons_processed}, Total payments: {total_payments}")
        
        # Log summary by season
        await self.log_season_summary()
        
        return self.payments_data

    async def log_season_summary(self):
        """Log a summary of payments by season."""
        try:
            season_counts = {}
            for record in self.payments_data:
                season = record.get('season', 'Unknown Season')
                season_counts[season] = season_counts.get(season, 0) + 1
            
            self.logger.info("=== SEASON SUMMARY ===")
            for season, count in season_counts.items():
                self.logger.info(f"Season '{season}': {count} payments")
            self.logger.info("=====================")
            
        except Exception as ex:
            self.logger.warning(f"Error creating season summary:", ex)

    async def scrape_season_pages(self, page, max_pages=50):
        """Scrape all pages for a specific season."""
        page_count = 0
        season_payments = 0
        
        while page_count < max_pages:
            page_count += 1
            self.logger.info(f"Processing page {page_count} for current season")
            
            # Extract payments from current page
            page_payments = await self.extract_payments_from_current_page(page)
            
            if not page_payments:
                self.logger.warning(f"No payments found on page {page_count}")
                break
            
            # Add to total data
            self.payments_data.extend(page_payments)
            season_payments += len(page_payments)
            
            self.logger.info(f"Page {page_count}: {len(page_payments)} payments extracted (Season total: {season_payments})")
            
            # Try to go to previous page
            if not await self.click_next_page(page=page):
                self.logger.info("No more pages available or previous button not found")
                break
            
            # Small delay between pages
            await page.wait_for_timeout(500)
        
        return season_payments
    
    def save_data(self, filename=None):
        """Save the scraped data to files."""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"payments_data_{timestamp}"
        
        # Save as JSON
        json_filename = f"{filename}.json"
        try:
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(self.payments_data, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Data saved to {json_filename}")
        except Exception as e:
            self.logger.error(f"Error saving JSON file:", e)
        
        # Save as CSV
        csv_filename = f"{filename}.csv"
        try:
            if self.payments_data:
                # Flatten the data for CSV
                flattened_data = []
                for record in self.payments_data:
                    flat_record = {
                        'row_number': record['row_number'],
                        'page_number': record['page_number'],
                        'timestamp': record['timestamp'],
                        'season': record.get('season', 'Unknown Season')
                    }
                    # Add all data columns
                    for key, value in record['data'].items():
                        flat_record[key] = value
                    flattened_data.append(flat_record)
                
                # Write CSV
                if flattened_data:
                    fieldnames = flattened_data[0].keys()
                    with open(csv_filename, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(flattened_data)
                    self.logger.info(f"Data saved to {csv_filename}")
        except Exception as e:
            self.logger.error(f"Error saving CSV file:", e)
    
async def main():
    """Main function to run the scraper."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Scrape payments records from a table using Playwright')
    parser.add_argument('url', help='URL of the page containing the payments table')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--max-pages', type=int, default=50, help='Maximum number of pages to scrape')
    parser.add_argument('--output', help='Output filename (without extension)')
    
    args = parser.parse_args()
    
    scraper = None
    try:
        # Initialize scraper
        import logging
        scraper = IfaPaymentScraper(logging)
        
        # Navigate to the page
        if not await scraper.navigate_to_page(args.url):
            scraper.logger.error("Failed to navigate to the target page")
            return 1
        
        # Scrape all pages
        total_payments = await scraper.scrape_all_pages(max_pages=args.max_pages)
        
        # Save data
        scraper.save_data(args.output)
        
        scraper.logger.info(f"Scraping completed successfully. Total payments extracted: {total_payments}")
        return 0
        
    except KeyboardInterrupt:
        scraper.logger.info("Scraping interrupted by user")
        return 1
    except Exception as e:
        scraper.logger.error(f"An error occurred:", e)
        return 1
    finally:
        pass

if __name__ == "__main__":
    asyncio.run(main())
