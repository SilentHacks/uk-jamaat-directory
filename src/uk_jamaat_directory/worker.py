from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from uk_jamaat_directory.config import get_settings

settings = get_settings()

celery_app = Celery(
    "uk_jamaat_directory",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_default_queue="directory",
    timezone="Europe/London",
    include=["uk_jamaat_directory.tasks.crawl"],
    beat_schedule={
        "crawl-register-sources": {
            "task": "uk_jamaat_directory.tasks.crawl.register_sources",
            "schedule": crontab(hour=3, minute=0),
        },
        "crawl-fetch-due-sources": {
            "task": "uk_jamaat_directory.tasks.crawl.fetch_due_sources",
            "schedule": crontab(minute=0),
        },
    },
)
