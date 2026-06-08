from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from uk_jamaat_directory.config import get_settings


@pytest.mark.asyncio
async def test_initial_migration_creates_core_tables(db_engine) -> None:  # noqa: ARG001
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")

    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get("DATABASE_URL", get_settings().database_url),
    )
    engine = create_async_engine(database_url)

    expected_tables = {
        "mosques",
        "mosque_sources",
        "schedule_candidates",
        "schedule_occurrences",
        "dataset_versions",
        "change_events",
        "source_artifacts",
        "source_extractor_assignments",
        "extractor_authoring_tasks",
        "mosque_claims",
        "corrections",
    }

    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            ),
        )
        table_names = {row.table_name for row in rows}

    await engine.dispose()

    assert expected_tables.issubset(table_names)
