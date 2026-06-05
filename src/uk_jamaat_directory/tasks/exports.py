from __future__ import annotations

import asyncio

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.exports import generate_dataset_exports
from uk_jamaat_directory.worker import celery_app


async def _generate_latest_exports_async() -> dict[str, object]:
    settings = get_settings()
    if not settings.export_enabled:
        return {"skipped": True, "reason": "export disabled"}

    async with cli_db_session(settings) as session:
        result = await generate_dataset_exports(session, settings=settings)
        await session.commit()

    return {
        "version": result.version,
        "files_written": result.files_written,
        "mosque_count": result.mosque_count,
        "occurrence_count": result.occurrence_count,
        "change_count": result.change_count,
        "checksum": result.checksum,
        "errors": result.errors,
    }


@celery_app.task(name="uk_jamaat_directory.tasks.exports.generate_latest")
def generate_latest_exports_task() -> dict[str, object]:
    return asyncio.run(_generate_latest_exports_async())
