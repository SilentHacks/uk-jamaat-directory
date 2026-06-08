from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.crawl.pipeline import process_source
from uk_jamaat_directory.ingest.extract.repo_extractors.runtime import (
    list_due_repo_extractor_source_ids,
    run_extractor_for_source,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.sync import (
    sync_repo_extractors,
)
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
    SourceExtractorAssignment,
)

FIXTURE_HTML = """<!doctype html>
<html><body>
<table>
  <tr><th>Date</th><th>Prayer</th><th>Adhan</th><th>Jamaat</th></tr>
  <tr><td>2099-06-09</td><td>Fajr</td><td>03:30</td><td>04:00</td></tr>
  <tr><td>2099-06-09</td><td>Dhuhr</td><td>13:00</td><td>13:30</td></tr>
  <tr><td>2099-06-12</td><td>Jumuah</td><td>13:00</td><td>13:30</td></tr>
</table>
</body></html>
"""


def _settings(**overrides: Any) -> Settings:
    base = Settings(
        environment="test",
        database_url="postgresql+asyncpg://x/y",
        crawl_enabled=True,
    )
    data = base.model_dump()
    data.update(overrides)
    return Settings(**data)


async def _active_mosque_and_source(db_session) -> tuple[Mosque, MosqueSource]:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Integration Synthetic Masjid",
        normalized_name="integration synthetic masjid",
        website_url="https://synthetic.example",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://synthetic.example",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    db_session.add(mosque)
    db_session.add(source)
    await db_session.flush()
    return mosque, source


async def _seed_assignment(db_session, source: MosqueSource) -> SourceExtractorAssignment:
    assignment = SourceExtractorAssignment(
        source_id=source.id,
        extractor_key="synthetic_html_table",
        extractor_version="2026.06.08.1",
        status="active",
        run_frequency="daily",
        run_timezone="Europe/London",
        next_run_at=datetime.now(UTC),
    )
    db_session.add(assignment)
    await db_session.flush()
    return assignment


@pytest.mark.asyncio
async def test_sync_creates_assignment_for_matching_source(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    _mosque, source = _active_mosque_and_source(db_session)

    result = await sync_repo_extractors(db_session)

    assignment = await db_session.get(SourceExtractorAssignment, source.id)
    assert assignment is not None
    assert assignment.extractor_key == "synthetic_html_table"
    assert assignment.status == "active"
    assert any(source.id == uuid.UUID(s.split("=")[0]) for s in result.upserted)


@pytest.mark.asyncio
async def test_sync_marks_missing_script(db_session, test_settings) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    _mosque, source = _active_mosque_and_source(db_session)
    assignment = await _seed_assignment(db_session, source)
    assignment.extractor_key = "removed_extractor"
    await db_session.flush()

    await sync_repo_extractors(db_session)

    await db_session.refresh(assignment)
    assert assignment.status == "missing_script"


@pytest.mark.asyncio
async def test_due_source_listing_uses_assignment(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    _mosque, source = _active_mosque_and_source(db_session)
    await _seed_assignment(db_session, source)

    settings = _settings(crawl_enabled=True)
    due = await list_due_repo_extractor_source_ids(db_session, settings=settings)
    assert source.id in due


@pytest.mark.asyncio
async def test_process_source_runs_repo_extractor(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    mosque, source = _active_mosque_and_source(db_session)
    await _seed_assignment(db_session, source)

    fetch_result = FetchResult(
        status_code=200,
        body=FIXTURE_HTML.encode("utf-8"),
        content_type="text/html",
        etag=None,
        last_modified=None,
        unchanged=False,
    )

    settings = _settings(
        crawl_enabled=True,
        repo_extractor_auto_approve_candidates=True,
    )

    with (
        patch(
            "uk_jamaat_directory.ingest.extract.repo_extractors.runtime.fetch_url",
            new=AsyncMock(return_value=fetch_result),
        ),
        patch(
            "uk_jamaat_directory.ingest.extract.repo_extractors.runtime.S3Storage.ensure_bucket",
            new=AsyncMock(),
        ),
        patch(
            "uk_jamaat_directory.ingest.extract.repo_extractors.runtime.S3Storage.put_bytes",
            new=AsyncMock(),
        ),
    ):
        result = await process_source(
            db_session, source.id, settings=settings, force=True
        )

    assert result.extracted is True
    assert result.candidates_created >= 3
    assert result.extractor_key == "synthetic_html_table"
    assert result.error is None

    candidates = (
        await db_session.execute(
            select(ScheduleCandidate).where(ScheduleCandidate.source_id == source.id)
        )
    ).scalars().all()
    prayers = sorted(c.prayer.value for c in candidates)
    assert "fajr" in prayers
    assert "jumuah" in prayers

    for candidate in candidates:
        assert candidate.evidence.get("contract") == "repo_site_extractor/v1"
        assert candidate.evidence.get("gate_passed") is True

    runs = (
        await db_session.execute(
            select(ExtractionRun).where(ExtractionRun.source_id == source.id)
        )
    ).scalars().all()
    assert any(r.extractor_version.startswith("repo:") for r in runs)

    assignment = await db_session.get(SourceExtractorAssignment, source.id)
    assert assignment is not None
    assert assignment.consecutive_failures == 0
    assert assignment.last_success_at is not None


@pytest.mark.asyncio
async def test_process_source_handles_fetch_failure(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    _mosque, source = _active_mosque_and_source(db_session)
    await _seed_assignment(db_session, source)

    fetch_result = FetchResult(
        status_code=200,
        body=b"",
        content_type=None,
        etag=None,
        last_modified=None,
        unchanged=False,
        error="robots.txt disallows fetch",
    )

    settings = _settings(crawl_enabled=True)

    with patch(
        "uk_jamaat_directory.ingest.extract.repo_extractors.runtime.fetch_url",
        new=AsyncMock(return_value=fetch_result),
    ):
        outcome = await run_extractor_for_source(db_session, source, settings=settings)

    assert outcome.status == "failed"
    assert "robots" in (outcome.error or "")

    assignment = await db_session.get(SourceExtractorAssignment, source.id)
    assert assignment is not None
    assert assignment.consecutive_failures == 1
    assert assignment.last_error is not None
