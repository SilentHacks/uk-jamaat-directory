from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from geoalchemy2 import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    ChangeEventType,
    Confidence,
    FreshnessStatus,
    MosqueStatus,
    Prayer,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.models.core import (
    ChangeEvent,
    DatasetVersion,
    Mosque,
    MosqueSource,
    ScheduleOccurrence,
)


async def seed_public_mosque_bundle(session: AsyncSession) -> dict[str, object]:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Test Masjid",
        normalized_name="test masjid",
        city="London",
        postcode="E1 1AA",
        location=WKTElement("POINT(-0.0759 51.5154)", srid=4326),
        status=MosqueStatus.ACTIVE,
    )
    public_source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MYLOCALMASJID,
        external_id="mlm-1",
        source_url="https://example.org/timetable",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.PARTNER_IMPORT,
        attribution="MyLocalMasjid",
        last_seen_at=datetime.now(UTC),
    )
    private_source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.PARTNER_FEED,
        external_id="private-1",
        publication_policy=SourcePublicationPolicy.PRIVATE_USE_ONLY,
        confidence=Confidence.COMMUNITY,
    )
    dataset_version = DatasetVersion(
        id=uuid.uuid4(),
        version="2026-06-04.1",
        schema_version="1.0",
        status="published",
        published_at=datetime.now(UTC),
        manifest={
            "attribution": ["UK Jamaat Directory"],
            "exports": {
                "ndjson": {
                    "url": "https://example.org/snapshots/latest.ndjson",
                    "checksum": "abc123",
                    "size_bytes": 1024,
                }
            },
        },
        checksum="dataset-checksum",
    )
    public_occurrence = ScheduleOccurrence(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_id=public_source.id,
        dataset_version_id=dataset_version.id,
        date=date(2026, 6, 5),
        prayer=Prayer.FAJR,
        start_time=time(2, 48),
        jamaat_time=time(3, 45),
        timezone="Europe/London",
        confidence=Confidence.PARTNER_IMPORT,
        freshness_status=FreshnessStatus.FRESH,
        source_url=public_source.source_url,
        last_verified_at=datetime.now(UTC),
    )
    private_occurrence = ScheduleOccurrence(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_id=private_source.id,
        dataset_version_id=dataset_version.id,
        date=date(2026, 6, 5),
        prayer=Prayer.DHUHR,
        jamaat_time=time(13, 15),
        timezone="Europe/London",
        confidence=Confidence.COMMUNITY,
        freshness_status=FreshnessStatus.NEEDS_REVIEW,
    )
    change_event = ChangeEvent(
        event_type=ChangeEventType.OCCURRENCE_PUBLISHED,
        mosque_id=mosque.id,
        occurrence_id=public_occurrence.id,
        dataset_version_id=dataset_version.id,
        payload={"prayer": "fajr"},
    )

    session.add(mosque)
    await session.flush()

    session.add_all([public_source, private_source, dataset_version])
    await session.flush()

    session.add_all([public_occurrence, private_occurrence])
    await session.flush()

    session.add(change_event)
    await session.commit()

    return {
        "mosque": mosque,
        "public_source": public_source,
        "private_source": private_source,
        "dataset_version": dataset_version,
        "public_occurrence": public_occurrence,
        "private_occurrence": private_occurrence,
        "change_event": change_event,
    }
