from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import (
    CandidateStatus,
    Confidence,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.crawl.pipeline import process_source
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import Mosque, MosqueSource, ScheduleCandidate

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/crawl"


@pytest.mark.asyncio
async def test_process_source_creates_candidates(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Pipeline Masjid",
        normalized_name="pipeline masjid",
        website_url="https://pipeline.example.org",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.STANDARD_FEED,
        external_id="pipeline.example.org",
        source_url="https://pipeline.example.org/.well-known/uk-jamaat-directory.json",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()

    feed_body = (FIXTURES / "standard_feed_valid.json").read_bytes()
    settings = Settings(
        **{
            **test_settings.model_dump(),
            "crawl_enabled": True,
            "crawl_validate_after_extract": True,
        }
    )

    fetch_result = FetchResult(
        status_code=200,
        body=feed_body,
        content_type="application/json",
        etag='"fixture"',
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
    assert result.extracted is True
    assert result.candidates_created > 0

    candidates = (
        (
            await db_session.execute(
                select(ScheduleCandidate).where(ScheduleCandidate.source_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    assert candidates
    assert all(candidate.status == CandidateStatus.PENDING for candidate in candidates)
