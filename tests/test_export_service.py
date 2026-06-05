from __future__ import annotations

import json
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
    uploaded: dict[str, bytes] = {}

    async def capture_upload(key: str, body: bytes, content_type: str) -> None:
        uploaded[key] = body

    with (
        patch(
            "uk_jamaat_directory.exports.service.S3Storage.put_bytes",
            new=AsyncMock(side_effect=capture_upload),
        ),
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

    manifest_key = next(key for key in uploaded if key.endswith("/manifest.json"))
    manifest_payload = json.loads(uploaded[manifest_key])
    assert manifest_payload["exports"] == exports


@pytest.mark.asyncio
async def test_generate_exports_excludes_restricted_occurrences(db_session, test_settings) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    version = bundle["dataset_version"]
    settings = Settings(
        **{**test_settings.model_dump(), "public_base_url": "http://localhost:8000"}
    )
    uploaded: dict[str, bytes] = {}

    async def capture_upload(key: str, body: bytes, content_type: str) -> None:
        uploaded[key] = body

    with (
        patch(
            "uk_jamaat_directory.exports.service.S3Storage.put_bytes",
            new=AsyncMock(side_effect=capture_upload),
        ),
        patch("uk_jamaat_directory.exports.service.S3Storage.ensure_bucket", new=AsyncMock()),
    ):
        result = await generate_dataset_exports(
            db_session,
            version_id=version.id,
            settings=settings,
        )

    assert result.occurrence_count == 1
    snapshot_key = next(key for key in uploaded if key.endswith("/snapshot.ndjson"))
    snapshot_text = uploaded[snapshot_key].decode("utf-8")
    assert "dhuhr" not in snapshot_text
    assert "partner_feed" not in snapshot_text

    mosque_record = json.loads(snapshot_text.strip().splitlines()[0])
    assert len(mosque_record["sources"]) == 1


@pytest.mark.asyncio
async def test_generate_exports_rejects_unpublished_version(db_session, test_settings) -> None:
    draft = DatasetVersion(
        version="2026-06-04.draft",
        schema_version="1.0",
        status="draft",
    )
    db_session.add(draft)
    await db_session.flush()

    settings = Settings(**test_settings.model_dump())
    with (
        patch("uk_jamaat_directory.exports.service.S3Storage.put_bytes", new=AsyncMock()),
        patch("uk_jamaat_directory.exports.service.S3Storage.ensure_bucket", new=AsyncMock()),
    ):
        result = await generate_dataset_exports(
            db_session,
            version_id=draft.id,
            settings=settings,
        )

    assert result.errors == ["dataset version is not published"]
    assert result.files_written == 0


@pytest.mark.asyncio
async def test_partial_upload_leaves_manifest_unchanged(db_session, test_settings) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    version = bundle["dataset_version"]
    original_checksum = version.checksum
    original_exports = dict((version.manifest or {}).get("exports", {}))

    settings = Settings(**test_settings.model_dump())
    put_mock = AsyncMock(side_effect=[None, None, RuntimeError("S3 failure")])

    with (
        patch("uk_jamaat_directory.exports.service.S3Storage.put_bytes", new=put_mock),
        patch("uk_jamaat_directory.exports.service.S3Storage.ensure_bucket", new=AsyncMock()),
        pytest.raises(RuntimeError, match="S3 failure"),
    ):
        await generate_dataset_exports(
            db_session,
            version_id=version.id,
            settings=settings,
        )

    refreshed = await db_session.scalar(
        select(DatasetVersion).where(DatasetVersion.id == version.id)
    )
    assert refreshed is not None
    assert refreshed.checksum == original_checksum
    assert refreshed.manifest.get("exports", {}) == original_exports
