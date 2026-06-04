from __future__ import annotations

from pathlib import Path

import pytest
from fixtures import seed_public_mosque_bundle
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.sources.mylocalmasjid import (
    build_coverage_report,
    import_mylocalmasjid_bundle,
    parse_file,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid.adapter import JsonFeedAdapter
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
async def test_private_import_does_not_overwrite_public_mosque_fields(
    db_session: AsyncSession,
    client_with_db: AsyncClient,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    mosque = bundle["mosque"]
    payload = """
    {
      "mosques": [{
        "external_id": "mlm-1",
        "name": "Restricted Private Masjid",
        "city": "Birmingham",
        "postcode": "B1 1AA",
        "schedules": []
      }]
    }
    """

    await import_mylocalmasjid_bundle(
        db_session,
        JsonFeedAdapter().parse(payload),
        raw_payload=payload.encode(),
        fetched_url="file://restricted-private-mlm.json",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    list_response = await client_with_db.get("/v1/mosques")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["items"][0]["name"] == "Test Masjid"
    assert list_payload["items"][0]["city"] == "London"

    detail_response = await client_with_db.get(f"/v1/mosques/{mosque.id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["name"] == "Test Masjid"
    assert detail_payload["postcode"] == "E1 1AA"


@pytest.mark.asyncio
async def test_reimport_same_payload_does_not_duplicate_candidates(
    db_session: AsyncSession,
) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    raw_payload = path.read_bytes()

    first = await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=raw_payload,
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    second = await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=raw_payload,
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    candidate_count = await db_session.scalar(
        select(func.count())
        .select_from(ScheduleCandidate)
        .join(MosqueSource)
        .where(MosqueSource.source_type == SourceType.MYLOCALMASJID)
    )
    assert first.candidates_created == 5
    assert second.artifacts_created == 0
    assert second.candidates_created == 0
    assert candidate_count == 5


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
