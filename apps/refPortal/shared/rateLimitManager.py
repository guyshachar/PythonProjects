import time
import asyncio
from shared.logger import Logger
from shared.db.dbClientBase import DbClientBase


class RateLimitManager:
    def __init__(self, logger: Logger, rateLimits: dict, db_client: DbClientBase):
        self.logger = logger
        self.rateLimits = rateLimits
        self.db_client = db_client
        self.semaphore = asyncio.Semaphore(5)

    def get_window_start(self, now: int, window_size: int) -> str:
        return str(now - (now % window_size))

    async def wait_until_allowed(self, action: str, max_retries: int = 5, base_delay: float = 1.0) -> bool:
        if action not in self.rateLimits:
            return True

        limit, period = self.rateLimits[action]

        for attempt in range(max_retries):
            now = int(time.time())
            window = self.get_window_start(now, period)
            ttl_seconds = period * 2  # keep the window row for two periods

            try:
                allowed = self.db_client.incrementRateLimit(
                    action=action, window=window, limit=limit, ttl_seconds=ttl_seconds
                )
            except Exception as ex:
                self.logger.error(f'[RateLimit] incrementRateLimit error for {action}:', ex)
                return True  # fail-open on unexpected errors

            if allowed:
                return True

            delay = base_delay * (2 ** attempt)
            self.logger.debug(f'[RateLimit] {action} blocked on attempt {attempt + 1}, retrying in {delay:.1f}s...')
            await asyncio.sleep(delay)

        self.logger.warning(f'[RateLimit] {action} giving up after {max_retries} retries.')
        return False
