from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.crawl.register import ensure_standard_feed_sources
from uk_jamaat_directory.models.core import Mosque, MosqueSource, SourceHealth


@pytest.mark.asyncio
async def test_register_creates_standard_feed_source(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Feed Test Masjid",
        normalized_name="feed test masjid",
        website_url="https://feed-test.example.org",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add(mosque)
    await db_session.flush()

    settings = Settings(
        **{
            **test_settings.model_dump(),
            "standard_feed_path": "/.well-known/uk-jamaat-directory.json",
        }
    )
    result = await ensure_standard_feed_sources(db_session, settings=settings)

    assert result.created == 1
    source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.mosque_id == mosque.id,
            MosqueSource.source_type == SourceType.STANDARD_FEED,
        )
    )
    assert source is not None
    assert source.external_id == "feed-test.example.org"
    assert source.source_url == "https://feed-test.example.org/.well-known/uk-jamaat-directory.json"
    assert source.publication_policy == SourcePublicationPolicy.UNKNOWN


@pytest.mark.asyncio
async def test_register_skips_mosque_with_recent_mlm(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="MLM Covered Masjid",
        normalized_name="mlm covered masjid",
        website_url="https://mlm-covered.example.org",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add(mosque)
    await db_session.flush()

    mlm_source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MYLOCALMASJID,
        external_id="mlm-001",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.PARTNER_IMPORT,
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(mlm_source)
    db_session.add(
        SourceHealth(
            source_id=mlm_source.id,
            last_success_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    await db_session.flush()

    result = await ensure_standard_feed_sources(db_session, settings=test_settings)
    assert result.skipped_mlm == 1
    assert result.created == 0
