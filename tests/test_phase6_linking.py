from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.sources.muslimsinbritain import (
    import_muslimsinbritain_bundle,
    parse_mib_file,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid import import_mylocalmasjid_bundle, parse_file
from uk_jamaat_directory.ingest.sources.openstreetmap import (
    import_openstreetmap_bundle,
    parse_osm_file,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource

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

    mosque_count_before = await db_session.scalar(select(func.count()).select_from(Mosque))

    mib_bundle = parse_mib_file(MIB_FIXTURE)
    result = await import_muslimsinbritain_bundle(
        db_session,
        mib_bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    mosque_count_after = await db_session.scalar(select(func.count()).select_from(Mosque))
    assert mosque_count_after == mosque_count_before + 2
    assert result.mosques_linked >= 1

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
