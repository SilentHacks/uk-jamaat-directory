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
from uk_jamaat_directory.ingest.crawl.register import ensure_crawl_sources
from uk_jamaat_directory.models.core import Mosque, MosqueSource, SourceHealth


@pytest.mark.asyncio
async def test_creates_mosque_website_for_active_mosque(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Website Test Masjid",
        normalized_name="website test masjid",
        website_url="https://website-test.example.org/some/path",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add(mosque)
    await db_session.flush()

    result = await ensure_crawl_sources(db_session, settings=test_settings)

    assert result.created_mosque_website == 1
    assert result.skipped_existing == 0
    assert result.created == 1

    source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.mosque_id == mosque.id,
            MosqueSource.source_type == SourceType.MOSQUE_WEBSITE,
        )
    )
    assert source is not None
    assert source.external_id == f"web-{mosque.id}"
    assert source.source_url == "https://website-test.example.org/some/path"
    assert source.publication_policy == SourcePublicationPolicy.UNKNOWN
    assert source.confidence == Confidence.OFFICIAL_IMPORT
    assert source.metadata_["crawl_enabled"] is True
    assert source.metadata_["homepage_url"] == "https://website-test.example.org/some/path"
    assert "profile_status" not in source.metadata_
    assert source.metadata_["allowed_crawl_paths"] == ["/"]


@pytest.mark.asyncio
async def test_skips_non_active_mosque(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Needs Review Masjid",
        normalized_name="needs review masjid",
        website_url="https://needs-review.example.org",
        status=MosqueStatus.NEEDS_REVIEW,
    )
    db_session.add(mosque)
    await db_session.flush()

    result = await ensure_crawl_sources(db_session, settings=test_settings)

    assert result.created_mosque_website == 0
    assert result.skipped_existing == 0


@pytest.mark.asyncio
async def test_skips_existing_crawl_source(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Already Registered Masjid",
        normalized_name="already registered masjid",
        website_url="https://already-registered.example.org",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add(mosque)
    await db_session.flush()

    existing_source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://already-registered.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(existing_source)
    await db_session.flush()

    result = await ensure_crawl_sources(db_session, settings=test_settings)

    assert result.created_mosque_website == 0
    assert result.skipped_existing == 1


@pytest.mark.asyncio
async def test_skips_recent_mlm(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="MLM Covered Website Masjid",
        normalized_name="mlm covered website masjid",
        website_url="https://mlm-covered-website.example.org",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add(mosque)
    await db_session.flush()

    mlm_source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MYLOCALMASJID,
        external_id="mlm-002",
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

    result = await ensure_crawl_sources(db_session, settings=test_settings)

    assert result.skipped_mlm == 1
    assert result.created_mosque_website == 0


@pytest.mark.asyncio
async def test_shared_domain_creates_separate_mosque_website(db_session, test_settings) -> None:
    mosque_a = Mosque(
        id=uuid.uuid4(),
        name="Shared Domain Masjid A",
        normalized_name="shared domain masjid a",
        website_url="https://shared.example.org/masjid-a",
        status=MosqueStatus.ACTIVE,
    )
    mosque_b = Mosque(
        id=uuid.uuid4(),
        name="Shared Domain Masjid B",
        normalized_name="shared domain masjid b",
        website_url="https://shared.example.org/masjid-b",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add_all([mosque_a, mosque_b])
    await db_session.flush()

    result = await ensure_crawl_sources(db_session, settings=test_settings)

    assert result.created_mosque_website == 2

    sources = (
        (
            await db_session.execute(
                select(MosqueSource).where(
                    MosqueSource.source_type == SourceType.MOSQUE_WEBSITE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(sources) == 2
    external_ids = {s.external_id for s in sources}
    assert external_ids == {f"web-{mosque_a.id}", f"web-{mosque_b.id}"}


@pytest.mark.asyncio
async def test_dry_run_does_not_write(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Dry Run Masjid",
        normalized_name="dry run masjid",
        website_url="https://dry-run.example.org",
        status=MosqueStatus.ACTIVE,
    )
    db_session.add(mosque)
    await db_session.flush()

    result = await ensure_crawl_sources(db_session, settings=test_settings, dry_run=True)

    assert result.created_mosque_website == 1

    source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.mosque_id == mosque.id,
            MosqueSource.source_type == SourceType.MOSQUE_WEBSITE,
        )
    )
    assert source is None


@pytest.mark.asyncio
async def test_limit_restricts_mosques_processed(db_session, test_settings) -> None:
    for i in range(3):
        db_session.add(
            Mosque(
                id=uuid.uuid4(),
                name=f"Limit Test Masjid {i}",
                normalized_name=f"limit test masjid {i}",
                website_url=f"https://limit-test-{i}.example.org",
                status=MosqueStatus.ACTIVE,
            )
        )
    await db_session.flush()

    result = await ensure_crawl_sources(db_session, settings=test_settings, limit=2)

    assert result.created_mosque_website == 2


@pytest.mark.asyncio
async def test_list_due_includes_mosque_website(db_session, test_settings) -> None:
    from uk_jamaat_directory.ingest.crawl.pipeline import list_due_source_ids

    mosque = Mosque(
        id=uuid.uuid4(),
        name="Due List Masjid",
        normalized_name="due list masjid",
        website_url="https://due-list.example.org",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://due-list.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add_all([mosque, source])
    await db_session.flush()

    settings = Settings(**{**test_settings.model_dump(), "crawl_enabled": True})
    due_ids = await list_due_source_ids(db_session, settings=settings)

    assert source.id in due_ids
