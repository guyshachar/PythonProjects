import asyncio
import logging

class PageManager:
    def __init__(self, num_pages):
        self.logger = logging.getLogger(__name__)

        self.page_queue = None
        self.page_list = None
        self.browser = None
        self.num_pages = num_pages

    async def initialize_pages(self, browser):
        self.browser = browser
        self.page_list = []
        self.page_queue = asyncio.Queue()

        for _ in range(self.num_pages):
            context = await self.browser.new_context()
            page = await context.new_page()  # Create a new page
            #page.set_default_timeout(60000)
            self.page_list.append(page)
            #page.on("crash", lambda: lambda: asyncio.create_task(handle_crash()))
            semaphore = asyncio.Semaphore(1)  # Protect this page with a semaphore
            self.page_queue.put_nowait((semaphore, page))

    async def acquire_page(self):
        self.logger.debug(f'wait for aquire page')
        semaphore, page = await self.page_queue.get()
        self.logger.debug(f'aquired page received')
        await semaphore.acquire()  # Lock the semaphore for this page
        return semaphore, page

    def release_page(self, semaphore, page):
        semaphore.release()  # Unlock the semaphore
        self.page_queue.put_nowait((semaphore, page))  # Return it to the queue

    async def renew_page(self, semaphore, page):
        semaphore.release()  # Unlock the semaphore
        context = page.context
        await page.close()
        await context.close()
        page = None
        context = await self.browser.new_context()
        page = await context.new_page()
        self.page_queue.put_nowait((semaphore, page))  # Add it to the queue

    def get_page(self, i):
        page = self.page_list[i]
        return page