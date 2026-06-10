import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "scoutcut",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["web.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,   # one video job at a time per worker process
    task_soft_time_limit=7200,      # 2 h soft limit
    task_time_limit=7800,           # 2 h 10 min hard limit
)
