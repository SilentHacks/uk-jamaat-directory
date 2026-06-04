from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    CandidateStatus,
    ChangeEventType,
    ExtractionKind,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid import import_mylocalmasjid_bundle, parse_file
from uk_jamaat_directory.models.core import (
    ChangeEvent,
    DatasetVersion,
    ExtractionRun,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
    ScheduleOccurrence,
)
from uk_jamaat_directory.schedules.publication import publish_candidates, validate_candidates
from uk_jamaat_directory.services.public_reads import PUBLISHED_DATASET_STATUS

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/mylocalmasjid"


@pytest.mark.asyncio
async def test_publish_blocked_for_unknown_policy(db_session: AsyncSession) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        validate_after_import=True,
    )
    await db_session.commit()

    await validate_candidates(db_session)
    result = await publish_candidates(db_session)
    await db_session.commit()

    assert result.published == 0
    assert result.skipped_policy > 0
    count = await db_session.scalar(select(func.count()).select_from(ScheduleOccurrence))
    assert count == 0


@pytest.mark.asyncio
async def test_publish_e2e_public_api(
    db_session: AsyncSession,
    client_with_db: AsyncClient,
) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    import_result = await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        validate_after_import=True,
    )
    await db_session.commit()
    assert import_result.candidates_created >= 1

    for mosque in (await db_session.execute(select(Mosque))).scalars().all():
        mosque.status = MosqueStatus.ACTIVE
    await db_session.commit()

    approved = await db_session.scalar(
        select(func.count())
        .select_from(ScheduleCandidate)
        .where(ScheduleCandidate.status == CandidateStatus.APPROVED)
    )
    assert approved >= 1

    publish_result = await publish_candidates(db_session)
    await db_session.commit()
    assert publish_result.published >= 1
    assert publish_result.dataset_version is not None

    source = await db_session.scalar(
        select(MosqueSource).where(MosqueSource.source_type == SourceType.MYLOCALMASJID).limit(1)
    )
    assert source is not None

    times_before = await client_with_db.get(
        f"/v1/mosques/{source.mosque_id}/times",
        params={"from": "2026-06-05", "to": "2026-06-05"},
    )
    assert times_before.status_code == 200
    assert len(times_before.json()["items"]) >= 1

    changes = await db_session.scalar(
        select(func.count())
        .select_from(ChangeEvent)
        .where(ChangeEvent.event_type == ChangeEventType.OCCURRENCE_PUBLISHED)
    )
    assert changes >= 1


@pytest.mark.asyncio
async def test_republish_uses_latest_dataset_only(
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
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        validate_after_import=True,
    )
    await db_session.commit()

    for mosque in (await db_session.execute(select(Mosque))).scalars().all():
        mosque.status = MosqueStatus.ACTIVE
    await db_session.commit()

    first = await publish_candidates(db_session)
    await db_session.commit()
    assert first.published >= 1

    await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        validate_after_import=True,
    )
    await db_session.commit()

    second = await publish_candidates(db_session)
    await db_session.commit()
    assert second.published >= 1

    source = await db_session.scalar(
        select(MosqueSource).where(MosqueSource.source_type == SourceType.MYLOCALMASJID).limit(1)
    )
    assert source is not None

    response = await client_with_db.get(
        f"/v1/mosques/{source.mosque_id}/times",
        params={"from": "2026-06-05", "to": "2026-06-05"},
    )
    payload = response.json()
    fajr_rows = [item for item in payload["items"] if item["prayer"] == "fajr"]
    assert len(fajr_rows) == 1
    assert fajr_rows[0]["dataset_version"] == second.dataset_version

    versions = (
        await db_session.execute(
            select(DatasetVersion).where(DatasetVersion.status == PUBLISHED_DATASET_STATUS)
        )
    ).scalars().all()
    assert len(versions) >= 2


@pytest.mark.asyncio
async def test_ai_candidate_not_auto_approved(db_session: AsyncSession) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
    )
    candidate = await db_session.scalar(select(ScheduleCandidate).limit(1))
    assert candidate is not None

    run = await db_session.get(ExtractionRun, candidate.extraction_run_id)
    assert run is not None
    run.kind = ExtractionKind.AI
    await db_session.flush()

    await validate_candidates(db_session)
    await db_session.refresh(candidate)
    assert candidate.status == CandidateStatus.PENDING
