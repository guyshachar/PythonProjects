import os

from celery import Celery
from web.config import settings

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "scoutcut",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["web.tasks"],
)

_soft_limit = settings.task_time_limit_hours * 3600
_hard_limit = _soft_limit + 600  # 10 min grace for cleanup

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # one video job at a time per worker process
    task_soft_time_limit=_soft_limit,
    task_time_limit=_hard_limit,
)
