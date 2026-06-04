from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    ArtifactStatus,
    CandidateStatus,
    Confidence,
    ExtractionKind,
    FreshnessStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.discovery.records import MatchDecision, ResolveOutcome
from uk_jamaat_directory.ingest.discovery.resolve import resolve_discovery_record
from uk_jamaat_directory.ingest.sources.mylocalmasjid.discovery import mlm_record_to_discovery
from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import (
    MyLocalMasjidImportBundle,
    MyLocalMasjidScheduleRow,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid.times import parse_hhmm
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
    SourceArtifact,
    SourceHealth,
)

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
) -> MyLocalMasjidImportResult:
    """Persist a parsed MyLocalMasjid bundle as private sources, artifacts, and candidates."""
    result = MyLocalMasjidImportResult()
    content_hash = hashlib.sha256(raw_payload).hexdigest()
    imported_at = datetime.now(UTC)

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

        artifact, artifact_created = await _record_artifact(
            session,
            source=source,
            fetched_url=fetched_url,
            content_hash=content_hash,
            raw_payload=raw_payload,
            object_key=store_artifact_object_key,
        )
        if artifact_created:
            result.artifacts_created += 1
        else:
            await _upsert_source_health(session, source_id=source.id, imported_at=imported_at)
            continue

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

    return result


async def _record_artifact(
    session: AsyncSession,
    *,
    source: MosqueSource,
    fetched_url: str,
    content_hash: str,
    raw_payload: bytes,
    object_key: str | None,
) -> tuple[SourceArtifact, bool]:
    existing = await session.scalar(
        select(SourceArtifact).where(
            SourceArtifact.source_id == source.id,
            SourceArtifact.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, False

    artifact = SourceArtifact(
        id=uuid.uuid4(),
        source_id=source.id,
        fetched_url=fetched_url,
        object_key=object_key,
        content_type="application/json",
        content_hash=content_hash,
        status=ArtifactStatus.FETCHED,
        fetched_at=datetime.now(UTC),
    )
    session.add(artifact)
    await session.flush()
    _ = raw_payload  # hash stored; object upload deferred to crawl phase
    return artifact, True


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
            candidate = ScheduleCandidate(
                id=uuid.uuid4(),
                mosque_id=mosque.id,
                source_id=source.id,
                extraction_run_id=extraction_run_id,
                date=row.date,
                prayer=row.prayer,
                start_time=start_time,
                jamaat_time=jamaat_time,
                session_number=row.session_number,
                session_label=row.session_label,
                timezone=row.timezone,
                confidence=Confidence.PARTNER_IMPORT,
                status=CandidateStatus.PENDING,
                evidence={
                    "source_type": SourceType.MYLOCALMASJID.value,
                    "external_id": source.external_id,
                    "linkback_url": source.metadata_.get("linkback_url"),
                },
            )
            session.add(candidate)
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
