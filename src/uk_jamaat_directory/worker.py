from __future__ import annotations

from celery import Celery

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
)
