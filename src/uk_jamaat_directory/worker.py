from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.observability import init_sentry

settings = get_settings()
init_sentry(settings)

celery_app = Celery(
    "uk_jamaat_directory",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_default_queue="directory",
    timezone="Europe/London",
    include=[
        "uk_jamaat_directory.tasks.crawl",
        "uk_jamaat_directory.tasks.exports",
        "uk_jamaat_directory.tasks.authoring",
        "uk_jamaat_directory.tasks.schedules",
    ],
    beat_schedule={
        "crawl-register-sources": {
            "task": "uk_jamaat_directory.tasks.crawl.register_sources",
            "schedule": crontab(hour=3, minute=0),
        },
        "crawl-fetch-due-sources": {
            "task": "uk_jamaat_directory.tasks.crawl.fetch_due_sources",
            "schedule": crontab(minute=0),
        },
        "exports-generate-latest": {
            "task": "uk_jamaat_directory.tasks.exports.generate_latest",
            "schedule": crontab(hour=4, minute=0),
        },
        "authoring-run-overnight": {
            "task": "uk_jamaat_directory.tasks.authoring.run_overnight",
            "schedule": crontab(hour=2, minute=0),
        },
    },
)
