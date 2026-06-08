from __future__ import annotations

import asyncio
import uuid
from typing import Any

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.ingest.authoring.orchestrator import (
    run_overnight_orchestrator,
)
from uk_jamaat_directory.worker import celery_app


async def _run_overnight_async(
    *,
    source_id: uuid.UUID | None,
    limit: int | None,
    concurrency: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    settings = get_settings()
    async with cli_db_session(settings) as session:
        summary = await run_overnight_orchestrator(
            session=session,
            settings=settings,
            source_id=source_id,
            limit=limit,
            concurrency=concurrency,
            dry_run=dry_run,
        )
        await session.commit()
    return summary.as_dict()


@celery_app.task(name="uk_jamaat_directory.tasks.authoring.run_overnight")
def run_overnight_task(
    *,
    source_id: str | None = None,
    limit: int | None = None,
    concurrency: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        _run_overnight_async(
            source_id=uuid.UUID(source_id) if source_id else None,
            limit=limit,
            concurrency=concurrency,
            dry_run=dry_run,
        )
    )
