from __future__ import annotations

import uuid
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
from uk_jamaat_directory.ingest.extract.ai.profiler import profile_mosque_website
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    Mosque,
    MosqueSource,
)


@pytest.mark.asyncio
async def test_profile_mosque_website_success(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Test Masjid",
        normalized_name="test masjid",
        city="London",
        postcode="SW1A 1AA",
        website_url="https://test-mosque.example.org",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://test-mosque.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True, "profile_status": "pending"},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()

    settings = Settings(
        **{
            **test_settings.model_dump(),
            "groq_api_key": "test-key",
            "ai_profiling_enabled": True,
        }
    )

    groq_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "{"
                        '"timetable_url": "/prayer-times", '
                        '"asset_type": "html_table", '
                        '"extraction_strategy": "css_selector", '
                        '"css_selector": ".prayer-times", '
                        '"confidence": 0.92, '
                        '"review_notes": "Clear timetable table found"'
                        "}"
                    )
                }
            }
        ]
    }

    with (
        patch(
            "uk_jamaat_directory.ingest.extract.ai.profiler.fetch_bounded_pages",
            new=AsyncMock(
                return_value=[
                    AsyncMock(
                        url="https://test-mosque.example.org",
                        body_snippet="<h1>Test Masjid</h1><table class='prayer-times'>...</table>",
                        content_type="text/html",
                        status_code=200,
                    )
                ]
            ),
        ),
        patch(
            "uk_jamaat_directory.ingest.extract.ai.profiler.groq_chat_completion",
            new=AsyncMock(return_value=groq_response),
        ),
    ):
        result = await profile_mosque_website(db_session, source.id, settings)

    assert result.profile is not None
    assert result.profile.asset_type == "html_table"
    assert result.profile.timetable_url == "/prayer-times"
    assert result.profile.confidence == 0.92
    assert result.extraction_run_id is not None

    # Source metadata updated
    await db_session.refresh(source)
    assert source.metadata_.get("profile_status") == "ready"
    assert source.metadata_.get("extraction_profile")["asset_type"] == "html_table"

    # ExtractionRun created
    run = (
        (
            await db_session.execute(
                select(ExtractionRun).where(ExtractionRun.source_id == source.id)
            )
        )
        .scalars()
        .first()
    )
    assert run is not None
    assert run.kind == ExtractionKind.AI
    assert float(run.score) == 0.92


@pytest.mark.asyncio
async def test_profile_mosque_website_low_confidence_review_needed(
    db_session, test_settings
) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Vague Mosque",
        normalized_name="vague mosque",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://vague.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()

    settings = Settings(
        **{
            **test_settings.model_dump(),
            "groq_api_key": "test-key",
            "ai_profiling_enabled": True,
        }
    )

    groq_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "{"
                        '"timetable_url": null, '
                        '"asset_type": "unknown", '
                        '"extraction_strategy": "unknown", '
                        '"confidence": 0.3, '
                        '"review_notes": "No timetable found"'
                        "}"
                    )
                }
            }
        ]
    }

    with (
        patch(
            "uk_jamaat_directory.ingest.extract.ai.profiler.fetch_bounded_pages",
            new=AsyncMock(
                return_value=[
                    AsyncMock(
                        url="https://vague.example.org",
                        body_snippet="<h1>Welcome</h1>",
                        content_type="text/html",
                        status_code=200,
                    )
                ]
            ),
        ),
        patch(
            "uk_jamaat_directory.ingest.extract.ai.profiler.groq_chat_completion",
            new=AsyncMock(return_value=groq_response),
        ),
    ):
        result = await profile_mosque_website(db_session, source.id, settings)

    assert result.profile is not None
    assert result.profile.confidence == 0.3
    await db_session.refresh(source)
    assert source.metadata_.get("profile_status") == "review_needed"


@pytest.mark.asyncio
async def test_profile_mosque_website_disabled_skips(db_session, test_settings) -> None:
    settings = Settings(
        **{
            **test_settings.model_dump(),
            "ai_profiling_enabled": False,
        }
    )

    result = await profile_mosque_website(db_session, uuid.uuid4(), settings)
    assert result.profile is None
    assert any("ai_profiling_enabled is False" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_profile_mosque_website_source_not_found(db_session, test_settings) -> None:
    settings = Settings(
        **{
            **test_settings.model_dump(),
            "groq_api_key": "test-key",
            "ai_profiling_enabled": True,
        }
    )

    result = await profile_mosque_website(db_session, uuid.uuid4(), settings)
    assert result.profile is None
    assert any("source not found" in e for e in result.errors)


@pytest.mark.asyncio
async def test_profile_mosque_website_no_pages(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="No Pages Mosque",
        normalized_name="no pages mosque",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://nopages.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()

    settings = Settings(
        **{
            **test_settings.model_dump(),
            "groq_api_key": "test-key",
            "ai_profiling_enabled": True,
        }
    )

    with patch(
        "uk_jamaat_directory.ingest.extract.ai.profiler.fetch_bounded_pages",
        new=AsyncMock(return_value=[]),
    ):
        result = await profile_mosque_website(db_session, source.id, settings)

    assert result.profile is None
    assert any("no fetchable HTML pages" in e for e in result.errors)


@pytest.mark.asyncio
async def test_profile_mosque_website_invalid_json_response(db_session, test_settings) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Bad JSON Mosque",
        normalized_name="bad json mosque",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://badjson.example.org",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()

    settings = Settings(
        **{
            **test_settings.model_dump(),
            "groq_api_key": "test-key",
            "ai_profiling_enabled": True,
        }
    )

    groq_response = {"choices": [{"message": {"content": "this is not json"}}]}

    with (
        patch(
            "uk_jamaat_directory.ingest.extract.ai.profiler.fetch_bounded_pages",
            new=AsyncMock(
                return_value=[
                    AsyncMock(
                        url="https://badjson.example.org",
                        body_snippet="<h1>Bad JSON Mosque</h1>",
                        content_type="text/html",
                        status_code=200,
                    )
                ]
            ),
        ),
        patch(
            "uk_jamaat_directory.ingest.extract.ai.profiler.groq_chat_completion",
            new=AsyncMock(return_value=groq_response),
        ),
    ):
        result = await profile_mosque_website(db_session, source.id, settings)

    assert result.profile is None
    assert any("AI profiling failed" in e for e in result.errors)
