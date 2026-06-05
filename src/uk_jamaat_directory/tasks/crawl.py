from __future__ import annotations

import asyncio
import uuid

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.ingest.crawl.pipeline import list_due_source_ids, process_source
from uk_jamaat_directory.ingest.crawl.register import ensure_standard_feed_sources
from uk_jamaat_directory.worker import celery_app


async def _register_sources_async() -> dict[str, int]:
    settings = get_settings()
    async with cli_db_session(settings) as session:
        result = await ensure_standard_feed_sources(session, settings=settings)
        await session.commit()
    return {
        "created": result.created,
        "skipped_existing": result.skipped_existing,
        "skipped_mlm": result.skipped_mlm,
        "skipped_no_domain": result.skipped_no_domain,
    }


async def _fetch_due_async() -> dict[str, int]:
    settings = get_settings()
    if not settings.crawl_enabled:
        return {"enqueued": 0}

    async with cli_db_session(settings) as session:
        due_ids = await list_due_source_ids(session, settings=settings)

    for source_id in due_ids:
        process_source_task.delay(str(source_id))

    return {"enqueued": len(due_ids)}


async def _process_source_async(source_id: uuid.UUID, *, force: bool = False) -> dict[str, object]:
    settings = get_settings()
    async with cli_db_session(settings) as session:
        result = await process_source(session, source_id, settings=settings, force=force)
        await session.commit()
    return {
        "source_id": str(result.source_id),
        "fetched": result.fetched,
        "unchanged": result.unchanged,
        "artifact_created": result.artifact_created,
        "extracted": result.extracted,
        "candidates_created": result.candidates_created,
        "skipped_reason": result.skipped_reason,
        "error": result.error,
        "warnings": result.warnings,
    }


@celery_app.task(name="uk_jamaat_directory.tasks.crawl.register_sources")
def register_sources_task() -> dict[str, int]:
    return asyncio.run(_register_sources_async())


@celery_app.task(name="uk_jamaat_directory.tasks.crawl.fetch_due_sources")
def fetch_due_sources_task() -> dict[str, int]:
    return asyncio.run(_fetch_due_async())


@celery_app.task(name="uk_jamaat_directory.tasks.crawl.process_source")
def process_source_task(source_id: str, *, force: bool = False) -> dict[str, object]:
    return asyncio.run(_process_source_async(uuid.UUID(source_id), force=force))
