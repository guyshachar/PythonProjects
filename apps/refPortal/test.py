import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        print("Hello1")
        browser = await p.chromium.launch(headless=True)
        print("Hello2")
        page = await browser.new_page()
        print("Hello3")
        await page.goto('https://example.com')
        await page.screenshot(path='example.png')
        await browser.close()

if __name__ == "__main__":
    print("Hello, World!")
    asyncio.run(run())
