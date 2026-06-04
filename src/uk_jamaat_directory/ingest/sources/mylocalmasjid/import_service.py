from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    ArtifactStatus,
    CandidateStatus,
    Confidence,
    ExtractionKind,
    FreshnessStatus,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import (
    MyLocalMasjidImportBundle,
    MyLocalMasjidMosqueRecord,
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
from uk_jamaat_directory.services.public_policy import is_public_source_policy

DEFAULT_ATTRIBUTION = "MyLocalMasjid"
EXTRACTOR_VERSION = "mylocalmasjid-deterministic-v1"


@dataclass
class MyLocalMasjidImportResult:
    mosques_upserted: int = 0
    sources_upserted: int = 0
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
        mosque, source = await _upsert_mosque_and_source(
            session,
            record,
            publication_policy=publication_policy,
            imported_at=imported_at,
        )
        result.mosques_upserted += 1
        result.sources_upserted += 1

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


async def _upsert_mosque_and_source(
    session: AsyncSession,
    record: MyLocalMasjidMosqueRecord,
    *,
    publication_policy: SourcePublicationPolicy,
    imported_at: datetime,
) -> tuple[Mosque, MosqueSource]:
    source = await _get_source(session, record.external_id)
    mosque: Mosque

    if source is not None and source.mosque_id is not None:
        mosque = await session.get_one(Mosque, source.mosque_id)
        if is_public_source_policy(publication_policy):
            _apply_mosque_fields(mosque, record)
    elif source is not None:
        mosque = _new_mosque(record)
        session.add(mosque)
        await session.flush()
        source.mosque_id = mosque.id
    else:
        mosque = _new_mosque(record)
        session.add(mosque)
        await session.flush()
        source = MosqueSource(
            id=uuid.uuid4(),
            mosque_id=mosque.id,
            source_type=SourceType.MYLOCALMASJID,
            external_id=record.external_id,
        )
        session.add(source)

    source.source_url = record.source_url
    source.display_name = record.name
    source.publication_policy = publication_policy
    source.confidence = Confidence.PARTNER_IMPORT
    source.attribution = record.attribution or DEFAULT_ATTRIBUTION
    source.last_seen_at = imported_at
    source.metadata_ = {
        "linkback_url": record.linkback_url,
        "profile_url": record.profile_url,
        "import_format_version": "1",
    }
    await session.flush()
    return mosque, source


async def _get_source(session: AsyncSession, external_id: str) -> MosqueSource | None:
    stmt = select(MosqueSource).where(
        MosqueSource.source_type == SourceType.MYLOCALMASJID,
        MosqueSource.external_id == external_id,
    )
    return await session.scalar(stmt)


def _new_mosque(record: MyLocalMasjidMosqueRecord) -> Mosque:
    mosque = Mosque(
        id=uuid.uuid4(),
        name=record.name,
        normalized_name=normalize_mosque_name(record.name),
        address_line1=record.address_line1,
        address_line2=record.address_line2,
        city=record.city,
        county=record.county,
        postcode=record.postcode,
        country=record.country,
        website_url=record.website_url,
        status=MosqueStatus.NEEDS_REVIEW,
    )
    _apply_location(mosque, record)
    return mosque


def _apply_mosque_fields(mosque: Mosque, record: MyLocalMasjidMosqueRecord) -> None:
    mosque.name = record.name
    mosque.normalized_name = normalize_mosque_name(record.name)
    mosque.address_line1 = record.address_line1
    mosque.address_line2 = record.address_line2
    mosque.city = record.city
    mosque.county = record.county
    mosque.postcode = record.postcode
    mosque.country = record.country
    mosque.website_url = record.website_url
    _apply_location(mosque, record)


def _apply_location(mosque: Mosque, record: MyLocalMasjidMosqueRecord) -> None:
    if record.latitude is not None and record.longitude is not None:
        mosque.location = WKTElement(
            f"POINT({record.longitude} {record.latitude})",
            srid=4326,
        )


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
