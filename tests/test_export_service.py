from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fixtures import seed_public_mosque_bundle
from sqlalchemy import select

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.exports import generate_dataset_exports
from uk_jamaat_directory.models.core import DatasetVersion


@pytest.mark.asyncio
async def test_generate_exports_updates_manifest(db_session, test_settings) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    version = bundle["dataset_version"]

    settings = Settings(
        **{**test_settings.model_dump(), "public_base_url": "http://localhost:8000"}
    )

    with (
        patch("uk_jamaat_directory.exports.service.S3Storage.put_bytes", new=AsyncMock()),
        patch("uk_jamaat_directory.exports.service.S3Storage.ensure_bucket", new=AsyncMock()),
    ):
        result = await generate_dataset_exports(
            db_session,
            version_id=version.id,
            settings=settings,
        )

    assert not result.errors
    assert result.files_written == 5
    assert result.occurrence_count == 1
    assert result.checksum is not None

    refreshed = await db_session.scalar(
        select(DatasetVersion).where(DatasetVersion.id == version.id)
    )
    assert refreshed is not None
    exports = refreshed.manifest.get("exports", {})
    assert "ndjson" in exports
    assert "csv" in exports
    assert "changes" in exports
    assert exports["ndjson"]["checksum"].startswith("sha256:")
    assert refreshed.checksum == exports["ndjson"]["checksum"]
    assert refreshed.manifest["source_counts"]["excluded_restricted"] == 1
