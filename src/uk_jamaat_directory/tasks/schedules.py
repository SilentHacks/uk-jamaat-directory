"""Celery tasks for schedule validation, publication, and freshness.

These wrap the same service functions the CLI uses so the admin UI can trigger
them asynchronously instead of blocking an HTTP request on a long publish.
"""

from __future__ import annotations

import asyncio
from typing import Any

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.schedules.freshness import recompute_all_source_health
from uk_jamaat_directory.schedules.publication import publish_candidates, validate_candidates
from uk_jamaat_directory.worker import celery_app


async def _validate_async() -> dict[str, Any]:
    settings = get_settings()
    async with cli_db_session(settings) as session:
        result = await validate_candidates(session, update_status=True, settings=settings)
        await session.commit()
    return {
        "examined": result.examined,
        "approved": result.approved,
        "rejected": result.rejected,
        "pending": result.pending,
        "skipped": result.skipped,
    }


async def _publish_async() -> dict[str, Any]:
    settings = get_settings()
    async with cli_db_session(settings) as session:
        result = await publish_candidates(session, settings=settings)
        await session.commit()
    return {
        "published": result.published,
        "carried_forward": result.carried_forward,
        "dataset_version": result.dataset_version,
        "removed": result.removed_occurrences,
        "skipped_policy": result.skipped_policy,
        "skipped_validation": result.skipped_validation,
        "errors": result.errors[:20],
    }


async def _recompute_freshness_async() -> dict[str, Any]:
    settings = get_settings()
    async with cli_db_session(settings) as session:
        count = await recompute_all_source_health(session)
        await session.commit()
    return {"recomputed_sources": count}


@celery_app.task(name="uk_jamaat_directory.tasks.schedules.validate_candidates")
def validate_candidates_task() -> dict[str, Any]:
    return asyncio.run(_validate_async())


@celery_app.task(name="uk_jamaat_directory.tasks.schedules.publish_candidates")
def publish_candidates_task() -> dict[str, Any]:
    return asyncio.run(_publish_async())


@celery_app.task(name="uk_jamaat_directory.tasks.schedules.recompute_freshness")
def recompute_freshness_task() -> dict[str, Any]:
    return asyncio.run(_recompute_freshness_async())
