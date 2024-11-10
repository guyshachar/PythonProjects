import logging
import asyncio
from playwright.async_api import async_playwright

async def run():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    async with async_playwright() as p:
        logger.info("Hello1")
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox','--disable-gpu','--single-process'])
        logger.info("Hello2")
        page = await browser.new_page()
        logger.info("Hello3")
        await page.goto('https://example.com')
        await page.screenshot(path='example.png')
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
