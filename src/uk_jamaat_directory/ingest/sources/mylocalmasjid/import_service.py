from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    ExtractionKind,
    FreshnessStatus,
    SourcePublicationPolicy,
)
from uk_jamaat_directory.ingest.artifacts import record_fetched_artifact
from uk_jamaat_directory.ingest.discovery.records import MatchDecision, ResolveOutcome
from uk_jamaat_directory.ingest.discovery.resolve import resolve_discovery_record
from uk_jamaat_directory.ingest.sources.mylocalmasjid.discovery import mlm_record_to_discovery
from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import (
    MyLocalMasjidImportBundle,
    MyLocalMasjidScheduleRow,
)
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    Mosque,
    MosqueSource,
    SourceHealth,
)
from uk_jamaat_directory.schedules.candidates import upsert_schedule_candidate
from uk_jamaat_directory.schedules.parse import parse_hhmm
from uk_jamaat_directory.schedules.publication import validate_candidates
from uk_jamaat_directory.schedules.types import ScheduleCandidateInput

EXTRACTOR_VERSION = "mylocalmasjid-deterministic-v1"


@dataclass
class MyLocalMasjidImportResult:
    mosques_upserted: int = 0
    sources_upserted: int = 0
    mosques_linked: int = 0
    reviews_created: int = 0
    artifacts_created: int = 0
    candidates_created: int = 0
    candidates_skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def import_mylocalmasjid_bundle(
    session: AsyncSession,
    bundle: MyLocalMasjidImportBundle,
    *,
    raw_payload: bytes,
    fetched_url: str,
    publication_policy: SourcePublicationPolicy,
    store_artifact_object_key: str | None = None,
    validate_after_import: bool = False,
) -> MyLocalMasjidImportResult:
    """Persist a parsed MyLocalMasjid bundle as private sources, artifacts, and candidates."""
    result = MyLocalMasjidImportResult()
    imported_at = datetime.now(UTC)
    affected_source_ids: set[uuid.UUID] = set()

    for record in bundle.mosques:
        try:
            async with session.begin_nested():
                discovery = mlm_record_to_discovery(record, publication_policy=publication_policy)
                resolved = await resolve_discovery_record(session, discovery)
        except (ValueError, SQLAlchemyError) as exc:
            result.errors.append(f"{record.external_id}: {exc}")
            continue

        result.sources_upserted += 1
        if resolved.match.decision == MatchDecision.NEEDS_REVIEW:
            result.reviews_created += 1
        elif resolved.outcome == ResolveOutcome.AUTO_LINK_MATCH:
            result.mosques_linked += 1
        if resolved.mosque is not None:
            result.mosques_upserted += 1
            mosque = resolved.mosque
            source = resolved.source
        else:
            continue

        artifact, artifact_created, _content_hash = await record_fetched_artifact(
            session,
            source,
            fetched_url=fetched_url,
            body=raw_payload,
            content_type="application/json",
            upload_to_s3=store_artifact_object_key is not None,
        )
        if store_artifact_object_key and artifact.object_key is None:
            artifact.object_key = store_artifact_object_key
            await session.flush()
        if artifact_created:
            result.artifacts_created += 1
            extraction_run = ExtractionRun(
                id=uuid.uuid4(),
                artifact_id=artifact.id,
                source_id=source.id,
                kind=ExtractionKind.DETERMINISTIC,
                extractor_version=EXTRACTOR_VERSION,
                status="succeeded",
                finished_at=imported_at,
                metadata_={"mosque_external_id": record.external_id},
            )
            session.add(extraction_run)
            await session.flush()
        else:
            extraction_run = await _latest_extraction_run(session, source_id=source.id)
            if extraction_run is None:
                extraction_run = ExtractionRun(
                    id=uuid.uuid4(),
                    artifact_id=artifact.id,
                    source_id=source.id,
                    kind=ExtractionKind.DETERMINISTIC,
                    extractor_version=EXTRACTOR_VERSION,
                    status="succeeded",
                    finished_at=imported_at,
                    metadata_={"mosque_external_id": record.external_id},
                )
                session.add(extraction_run)
                await session.flush()

        affected_source_ids.add(source.id)
        created, skipped = await _create_candidates(
            session,
            mosque=mosque,
            source=source,
            extraction_run_id=extraction_run.id,
            schedules=record.schedules,
        )
        result.candidates_created += created
        result.candidates_skipped += skipped

        await _upsert_source_health(session, source_id=source.id, imported_at=imported_at)

    if validate_after_import and affected_source_ids:
        await validate_candidates(session, source_ids=affected_source_ids)

    return result


async def _latest_extraction_run(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
) -> ExtractionRun | None:
    return await session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.source_id == source_id)
        .order_by(ExtractionRun.finished_at.desc().nullslast(), ExtractionRun.started_at.desc())
        .limit(1)
    )


async def _create_candidates(
    session: AsyncSession,
    *,
    mosque: Mosque,
    source: MosqueSource,
    extraction_run_id: uuid.UUID,
    schedules: list[MyLocalMasjidScheduleRow],
) -> tuple[int, int]:
    created = 0
    skipped = 0
    for row in schedules:
        try:
            jamaat_time = parse_hhmm(row.jamaat_time)
            if jamaat_time is None:
                skipped += 1
                continue
            start_time = parse_hhmm(row.start_time)
            candidate_input = ScheduleCandidateInput(
                date=row.date,
                prayer=row.prayer,
                session_number=row.session_number,
                session_label=row.session_label,
                timezone=row.timezone,
            )
            updated, unchanged = await upsert_schedule_candidate(
                session,
                mosque=mosque,
                source=source,
                extraction_run_id=extraction_run_id,
                row=candidate_input,
                jamaat_time=jamaat_time,
                start_time=start_time,
            )
            if unchanged:
                skipped += 1
            else:
                created += 1
        except ValueError:
            skipped += 1
    await session.flush()
    return created, skipped


async def _upsert_source_health(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    imported_at: datetime,
) -> None:
    health = await session.get(SourceHealth, source_id)
    if health is None:
        health = SourceHealth(
            source_id=source_id,
            freshness_status=FreshnessStatus.NEEDS_REVIEW,
        )
        session.add(health)
    health.last_success_at = imported_at
    health.freshness_status = FreshnessStatus.NEEDS_REVIEW
    health.message = "imported; awaiting validation and publication"
    await session.flush()
