from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import (
    Confidence,
    ExtractionKind,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.crawl.pipeline import process_source
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
    SourceArtifact,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/crawl"


@pytest.mark.asyncio
async def test_process_mosque_website_stores_artifact_no_candidates(
    db_session, test_settings
) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Website Masjid",
        normalized_name="website masjid",
        website_url="https://mosque-website.example.org",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://mosque-website.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()

    html_body = b"<html><body><h1>Mosque Website</h1></body></html>"
    settings = Settings(
        **{
            **test_settings.model_dump(),
            "crawl_enabled": True,
        }
    )

    fetch_result = FetchResult(
        status_code=200,
        body=html_body,
        content_type="text/html",
        etag=None,
        last_modified=None,
        unchanged=False,
    )

    with (
        patch(
            "uk_jamaat_directory.ingest.crawl.pipeline.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ),
        patch(
            "uk_jamaat_directory.ingest.artifacts.S3Storage.put_bytes",
            new=AsyncMock(),
        ),
        patch(
            "uk_jamaat_directory.ingest.artifacts.S3Storage.ensure_bucket",
            new=AsyncMock(),
        ),
    ):
        result = await process_source(db_session, source.id, settings=settings, force=True)

    assert result.fetched is True
    assert result.artifact_created is True
    assert result.extracted is False
    assert result.candidates_created == 0

    candidates = (
        (
            await db_session.execute(
                select(ScheduleCandidate).where(ScheduleCandidate.source_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(candidates) == 0


@pytest.mark.asyncio
async def test_process_mosque_website_reruns_extraction_on_unchanged_after_failure(
    db_session, test_settings
) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Retry Website Masjid",
        normalized_name="retry website masjid",
        website_url="https://retry-website.example.org",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://retry-website.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    artifact = SourceArtifact(
        id=uuid.uuid4(),
        source_id=source.id,
        fetched_url=source.source_url,
        object_key="artifacts/test/website.html",
        content_type="text/html",
        content_hash="abc123",
        etag='"fixture"',
    )
    failed_run = ExtractionRun(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        source_id=source.id,
        kind=ExtractionKind.DETERMINISTIC,
        extractor_version="none",
        status="failed",
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()
    db_session.add(artifact)
    await db_session.flush()
    db_session.add(failed_run)
    await db_session.flush()

    html_body = b"<html><body><h1>Mosque Website</h1></body></html>"
    settings = Settings(
        **{
            **test_settings.model_dump(),
            "crawl_enabled": True,
        }
    )
    fetch_result = FetchResult(
        status_code=304,
        body=b"",
        content_type=None,
        etag='"fixture"',
        last_modified=None,
        unchanged=True,
    )

    with (
        patch(
            "uk_jamaat_directory.ingest.crawl.pipeline.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ),
        patch(
            "uk_jamaat_directory.ingest.extract.runner.S3Storage.get_bytes",
            new=AsyncMock(return_value=html_body),
        ),
    ):
        result = await process_source(db_session, source.id, settings=settings, force=True)

    assert result.unchanged is True
    assert result.extracted is False
    assert result.candidates_created == 0
    assert result.error is not None  # no extractor → extraction fails
