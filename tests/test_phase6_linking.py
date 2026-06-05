from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.sources.muslimsinbritain import (
    import_muslimsinbritain_bundle,
    parse_mib_file,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import (
    MibImportBundle,
    MibMosqueRecord,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid import import_mylocalmasjid_bundle, parse_file
from uk_jamaat_directory.ingest.sources.openstreetmap import (
    import_openstreetmap_bundle,
    parse_osm_file,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.schema import OsmImportBundle, OsmPlaceRecord
from uk_jamaat_directory.models.core import IdentityMatchReview, Mosque, MosqueSource

OSM_FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/openstreetmap/sample_places.json"
MLM_FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/mylocalmasjid/sample_export.json"
MIB_FIXTURE = (
    Path(__file__).resolve().parents[1] / "data/fixtures/muslimsinbritain/sample_export.json"
)


@pytest.mark.asyncio
async def test_mlm_links_to_existing_osm_mosque(db_session: AsyncSession) -> None:
    osm_bundle = parse_osm_file(OSM_FIXTURE)
    await import_openstreetmap_bundle(db_session, osm_bundle)
    await db_session.commit()

    mosque_count_before = await db_session.scalar(select(func.count()).select_from(Mosque))

    mlm_bundle = parse_file(MLM_FIXTURE)
    result = await import_mylocalmasjid_bundle(
        db_session,
        mlm_bundle,
        raw_payload=MLM_FIXTURE.read_bytes(),
        fetched_url=f"file://{MLM_FIXTURE}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    mosque_count_after = await db_session.scalar(select(func.count()).select_from(Mosque))
    assert mosque_count_after == mosque_count_before
    assert result.mosques_linked >= 1

    mlm_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.MYLOCALMASJID,
            MosqueSource.external_id == "mlm-synth-001",
        )
    )
    osm_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.OPENSTREETMAP,
            MosqueSource.external_id == "node/900001",
        )
    )
    assert mlm_source is not None and osm_source is not None
    assert mlm_source.mosque_id == osm_source.mosque_id


@pytest.mark.asyncio
async def test_mib_links_to_existing_osm_mosque(db_session: AsyncSession) -> None:
    osm_bundle = parse_osm_file(OSM_FIXTURE)
    await import_openstreetmap_bundle(db_session, osm_bundle)
    await db_session.commit()

    mosque_count_before = int(
        await db_session.scalar(select(func.count()).select_from(Mosque)) or 0
    )

    mib_bundle = parse_mib_file(MIB_FIXTURE)
    result = await import_muslimsinbritain_bundle(
        db_session,
        mib_bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    mosque_count_after = await db_session.scalar(select(func.count()).select_from(Mosque))
    assert mosque_count_after == mosque_count_before + 1
    assert result.mosques_linked >= 1
    assert result.reviews_created >= 1

    mib_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN,
            MosqueSource.external_id == "mib-synth-001",
        )
    )
    osm_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.OPENSTREETMAP,
            MosqueSource.external_id == "node/900001",
        )
    )
    assert mib_source is not None and osm_source is not None
    assert mib_source.mosque_id == osm_source.mosque_id

    ie_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN,
            MosqueSource.external_id == "mib-synth-002",
        )
    )
    assert ie_source is not None
    assert ie_source.mosque_id != osm_source.mosque_id


@pytest.mark.asyncio
async def test_precise_close_geo_match_links_despite_postcode_and_name_mismatch(
    db_session: AsyncSession,
) -> None:
    osm_bundle = OsmImportBundle(
        exported_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        places=[
            OsmPlaceRecord(
                osm_type="node",
                osm_id=42,
                name="Old Road Islamic Centre",
                city="London",
                postcode="E2 1AA",
                latitude=51.5308,
                longitude=-0.0714,
                religion="muslim",
            )
        ],
    )
    await import_openstreetmap_bundle(db_session, osm_bundle)
    await db_session.commit()

    mosque_count_before = await db_session.scalar(select(func.count()).select_from(Mosque))
    mib_bundle = MibImportBundle(
        exported_at=datetime.fromisoformat("2026-01-02T00:00:00+00:00"),
        mosques=[
            MibMosqueRecord(
                external_id="mib-close-geo",
                name="Different Trust Name",
                city="London",
                postcode="E9 9ZZ",
                country="GB",
                latitude=51.5308,
                longitude=-0.0714,
                record_class="mosque",
                usage="full_time",
                location_precision="precise",
                metadata_confidence="high",
            )
        ],
    )
    result = await import_muslimsinbritain_bundle(
        db_session,
        mib_bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    mosque_count_after = await db_session.scalar(select(func.count()).select_from(Mosque))
    assert mosque_count_after == mosque_count_before
    assert result.mosques_linked == 1
    assert result.reviews_created == 0

    osm_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.OPENSTREETMAP,
            MosqueSource.external_id == "node/42",
        )
    )
    mib_source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN,
            MosqueSource.external_id == "mib-close-geo",
        )
    )
    assert osm_source is not None and mib_source is not None
    assert mib_source.mosque_id == osm_source.mosque_id


@pytest.mark.asyncio
async def test_reimport_auto_link_accepts_existing_pending_identity_review(
    db_session: AsyncSession,
) -> None:
    osm_bundle = OsmImportBundle(
        exported_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        places=[
            OsmPlaceRecord(
                osm_type="node",
                osm_id=44,
                name="Canonical Masjid",
                city="London",
                postcode="E2 1AA",
                latitude=51.5308,
                longitude=-0.0714,
                religion="muslim",
            )
        ],
    )
    await import_openstreetmap_bundle(db_session, osm_bundle)
    await db_session.commit()

    first_mib_bundle = MibImportBundle(
        exported_at=datetime.fromisoformat("2026-01-02T00:00:00+00:00"),
        mosques=[
            MibMosqueRecord(
                external_id="mib-review-then-link",
                name="Ambiguous Community Hall",
                city="London",
                postcode="E9 9ZZ",
                country="GB",
                latitude=51.5308,
                longitude=-0.0714,
                record_class="uncertain",
                usage="irregular",
                location_precision="approximate",
                metadata_confidence="low",
            )
        ],
    )
    first_result = await import_muslimsinbritain_bundle(
        db_session,
        first_mib_bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()
    assert first_result.reviews_created == 1

    source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN,
            MosqueSource.external_id == "mib-review-then-link",
        )
    )
    assert source is not None
    assert source.mosque_id is None

    pending_count = await db_session.scalar(
        select(func.count())
        .select_from(IdentityMatchReview)
        .where(
            IdentityMatchReview.source_id == source.id,
            IdentityMatchReview.status == "pending",
        )
    )
    assert pending_count == 1

    second_mib_bundle = MibImportBundle(
        exported_at=datetime.fromisoformat("2026-01-03T00:00:00+00:00"),
        mosques=[
            MibMosqueRecord(
                external_id="mib-review-then-link",
                name="Ambiguous Community Hall",
                city="London",
                postcode="E9 9ZZ",
                country="GB",
                latitude=51.5308,
                longitude=-0.0714,
                record_class="mosque",
                usage="full_time",
                location_precision="precise",
                metadata_confidence="high",
            )
        ],
    )
    second_result = await import_muslimsinbritain_bundle(
        db_session,
        second_mib_bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()
    assert second_result.mosques_linked == 1

    await db_session.refresh(source)
    assert source.mosque_id is not None

    pending_count = await db_session.scalar(
        select(func.count())
        .select_from(IdentityMatchReview)
        .where(
            IdentityMatchReview.source_id == source.id,
            IdentityMatchReview.status == "pending",
        )
    )
    accepted_count = await db_session.scalar(
        select(func.count())
        .select_from(IdentityMatchReview)
        .where(
            IdentityMatchReview.source_id == source.id,
            IdentityMatchReview.status == "accepted",
        )
    )
    assert pending_count == 0
    assert accepted_count == 1


@pytest.mark.asyncio
async def test_newer_public_source_name_replaces_existing_canonical_name(
    db_session: AsyncSession,
) -> None:
    osm_bundle = OsmImportBundle(
        exported_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        places=[
            OsmPlaceRecord(
                osm_type="node",
                osm_id=43,
                name="Older Public Name Mosque",
                city="London",
                postcode="E2 1AA",
                latitude=51.5308,
                longitude=-0.0714,
                religion="muslim",
                source_record_updated_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            )
        ],
    )
    await import_openstreetmap_bundle(db_session, osm_bundle)
    await db_session.commit()

    mib_bundle = MibImportBundle(
        exported_at=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
        mosques=[
            MibMosqueRecord(
                external_id="mib-newer-name",
                name="Newer Public Name Masjid",
                city="London",
                postcode="E2 1AA",
                country="GB",
                latitude=51.5308,
                longitude=-0.0714,
                record_class="mosque",
                usage="full_time",
                location_precision="precise",
                metadata_confidence="high",
                source_record_updated_at=datetime.fromisoformat("2026-06-01T00:00:00+00:00"),
            )
        ],
    )
    await import_muslimsinbritain_bundle(
        db_session,
        mib_bundle,
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
    )
    await db_session.commit()

    mosque = await db_session.scalar(select(Mosque).where(Mosque.postcode == "E2 1AA"))
    assert mosque is not None
    assert mosque.name == "Newer Public Name Masjid"


@pytest.mark.asyncio
async def test_export_timestamp_alone_does_not_replace_canonical_name(
    db_session: AsyncSession,
) -> None:
    osm_bundle = OsmImportBundle(
        exported_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        places=[
            OsmPlaceRecord(
                osm_type="node",
                osm_id=45,
                name="Source Dated OSM Mosque",
                city="London",
                postcode="E2 1AA",
                latitude=51.5308,
                longitude=-0.0714,
                religion="muslim",
                source_record_updated_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
            )
        ],
    )
    await import_openstreetmap_bundle(db_session, osm_bundle)
    await db_session.commit()

    mib_bundle = MibImportBundle(
        exported_at=datetime.fromisoformat("2026-12-01T00:00:00+00:00"),
        mosques=[
            MibMosqueRecord(
                external_id="mib-export-date-only",
                name="Export Date Only Name",
                city="London",
                postcode="E2 1AA",
                country="GB",
                latitude=51.5308,
                longitude=-0.0714,
                record_class="mosque",
                usage="full_time",
                location_precision="precise",
                metadata_confidence="high",
            )
        ],
    )
    await import_muslimsinbritain_bundle(
        db_session,
        mib_bundle,
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
    )
    await db_session.commit()

    mosque = await db_session.scalar(select(Mosque).where(Mosque.postcode == "E2 1AA"))
    assert mosque is not None
    assert mosque.name == "Source Dated OSM Mosque"
