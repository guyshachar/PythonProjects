import time
import boto3
from botocore.exceptions import ClientError
from pathlib import Path
import sys
import os
import asyncio
import functools
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared.logger import Logger

class RateLimitManager:
    def __init__(self, logger:Logger, rateLimits, dynamodbResource=None):
        try:
            self.logger = logger
            self.env = os.getenv('app_env')
            self.rateLimits = rateLimits
            
            self.rate_table = dynamodbResource.Table(f"rateLimiter_{self.env}")

            self.semaphore = asyncio.Semaphore(5)

        except Exception as ex:
            self.logger.error(f'Error in RateLimitManager init:', ex)

    def get_window_start(self, now, window_size):
        return str(now - (now % window_size))  # e.g. "1713260310"

    async def wait_until_allowed(self, action: str, max_retries: int = 5, base_delay: float = 1.0) -> bool:
        if action not in self.rateLimits:
            return True  # No rate limit defined

        limit, period = self.rateLimits[action]

        for attempt in range(max_retries):
            now = int(time.time())
            window = self.get_window_start(now, period)

            try:
                expireAt = now + 1 * 60 * 60  # seconds

                self.rate_table.update_item(
                    Key={"action": action, "window": window},
                    UpdateExpression="SET used = if_not_exists(used, :zero) + :one, expireAt = :ttl",
                    ConditionExpression="attribute_not_exists(used) OR used < :limit",
                    ExpressionAttributeValues={
                        ":zero": 0,
                        ":one": 1,
                        ":limit": limit,
                        ':ttl': {'N': str(expireAt)}
                    }
                )
                # ✅ Allowed
                return True

            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # ❌ Rate limit hit: backoff and retry
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    self.logger.debug(f"[RateLimit] Action {action} Blocked on attempt {attempt+1}, retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    raise  # Reraise unexpected errors

        self.logger.warning(f"[RateLimit] Action {action} Giving up after {max_retries} retries.")
        return False