import asyncio
import logging
import os

class PageManager:
    def __init__(self, logger:Logger, browser, num_pages):
        self.logger = logger
        self.browser = browser

        self.logger.info(f'PageManager starts...')

        self.page_queue = None
        self.page_list = None
        
        self.num_pages = num_pages
        self.timeout = int(os.getenv('timeout') or '5000')
        self.alwaysRenewPages = eval(os.getenv('alwaysRenewPages', 'False'))
        self.numOfCreates = 0
        self.numOfCloses = 0

        asyncio.create_task(self.initialize_pages())

    async def initialize_pages(self):
        self.page_list = []
        self.page_queue = asyncio.Queue()

        self.logger.debug(f'creates={self.numOfCreates} closes={self.numOfCloses}')

        self.numOfCreates = 0
        self.numOfCloses = 0
        
        for _ in range(self.num_pages):
            page = None
            if not self.alwaysRenewPages:
                page = await self.createPage()
                #page.set_default_timeout(60000)
                self.page_list.append(page)
            #page.on("crash", lambda: lambda: asyncio.create_task(handle_crash()))
            semaphore = asyncio.Semaphore(1)  # Protect this page with a semaphore
            self.page_queue.put_nowait((semaphore, page))

    async def dispose(self):
        self.logger.info(f'PageManager disposed')
        while True:
            try:
                semaphore, page = self.page_queue.get_nowait()
                if self.alwaysRenewPages:
                    await self.closePage(page)
                else:
                    await page.close()
                self.page_queue.task_done()
                self.logger.info(f'PageManager disposed')
            except asyncio.QueueEmpty:
                break

    async def createPage(self):
        self.numOfCreates += 1
        context = await self.browser.new_context()
        context.set_default_timeout(self.timeout)
        context.set_default_navigation_timeout(self.timeout * 2)
        page = await context.new_page()
        return page

    async def closePage(self, page):
        try:
            self.numOfCloses += 1
            context = page.context
            for page in context.pages:
                if not page.is_closed():
                    await page.close()
            all_pages_closed = all(page.is_closed() for page in context.pages)
            if all_pages_closed:
                #await context.clear_cookies()
                await context.close()
            page = None
        except Exception as ex:
            self.logger.error(f'closePage:', ex)
    
    async def acquire_page(self):
        self.logger.debug(f'wait for aquire page')
        semaphore, page = await self.page_queue.get()
        if self.alwaysRenewPages:
            page = await self.createPage()
        self.logger.debug(f'aquired page received')
        await semaphore.acquire()  # Lock the semaphore for this page
        return semaphore, page

    async def release_page(self, semaphore, page):
        semaphore.release()  # Unlock the semaphore
        if self.alwaysRenewPages:
            await self.closePage(page)
        self.page_queue.put_nowait((semaphore, page))  # Return it to the queue

    async def renew_page(self, semaphore, page):
        semaphore.release()  # Unlock the semaphore
        await self.closePage(page)
        page = await self.createPage()
        self.page_queue.put_nowait((semaphore, page))  # Add it to the queue

    def get_page(self, i):
        page = self.page_list[i]
        return page