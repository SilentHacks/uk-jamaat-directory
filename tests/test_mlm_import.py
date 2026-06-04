from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.sources.mylocalmasjid import (
    build_coverage_report,
    import_mylocalmasjid_bundle,
    parse_file,
)
from uk_jamaat_directory.models.core import MosqueSource, ScheduleCandidate, ScheduleOccurrence

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/mylocalmasjid"


@pytest.mark.asyncio
async def test_import_creates_candidates_without_public_occurrences(
    db_session: AsyncSession,
) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    raw = path.read_bytes()

    result = await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=raw,
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    assert result.mosques_upserted == 2
    assert result.candidates_created == 5
    assert result.errors == []

    occurrence_count = await db_session.scalar(select(func.count()).select_from(ScheduleOccurrence))
    assert occurrence_count == 0

    pending = await db_session.scalar(
        select(func.count())
        .select_from(ScheduleCandidate)
        .join(MosqueSource)
        .where(MosqueSource.source_type == SourceType.MYLOCALMASJID)
    )
    assert pending == 5


@pytest.mark.asyncio
async def test_import_with_private_policy_still_hidden_from_public_api(
    db_session: AsyncSession,
    client_with_db: AsyncClient,
) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.PRIVATE_USE_ONLY,
    )
    await db_session.commit()

    list_response = await client_with_db.get("/v1/mosques")
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 0


@pytest.mark.asyncio
async def test_coverage_report_after_import(db_session: AsyncSession) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    report = await build_coverage_report(db_session)
    assert report.source_count == 2
    assert report.pending_candidates == 5
    assert report.policy_counts["unknown"] == 2
