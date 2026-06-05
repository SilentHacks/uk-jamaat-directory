from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.sources.muslimsinbritain import (
    build_coverage_report,
    import_muslimsinbritain_bundle,
    parse_mib_file,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource

FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/muslimsinbritain/sample_export.json"


@pytest.mark.asyncio
async def test_import_mib_creates_private_sources(db_session: AsyncSession) -> None:
    bundle = parse_mib_file(FIXTURE)
    result = await import_muslimsinbritain_bundle(
        db_session,
        bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    assert result.records_processed == 3
    assert result.errors == []

    sources = (
        await db_session.scalars(
            select(MosqueSource).where(MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN)
        )
    ).all()
    assert len(sources) == 3
    assert {source.publication_policy for source in sources} == {SourcePublicationPolicy.UNKNOWN}
    assert {source.metadata_["country"] for source in sources} == {"GB", "IE"}

    first_source = next(source for source in sources if source.external_id == "mib-synth-001")
    assert first_source.metadata_["latitude"] == 51.5308
    assert first_source.metadata_["longitude"] == -0.0714
    assert first_source.metadata_["source_exported_at"] == "2026-06-05T10:00:00+00:00"


@pytest.mark.asyncio
async def test_mib_unknown_policy_does_not_overwrite_existing_public_fields(
    db_session: AsyncSession,
) -> None:
    mosque = Mosque(
        name="Synthetic OSM Central Masjid",
        normalized_name="synthetic osm central masjid",
        city="London",
        postcode="E2 1AA",
        country="GB",
        website_url="https://canonical.example.org",
    )
    db_session.add(mosque)
    await db_session.commit()

    bundle = parse_mib_file(FIXTURE)
    await import_muslimsinbritain_bundle(
        db_session,
        bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()
    await db_session.refresh(mosque)

    assert mosque.website_url == "https://canonical.example.org"


@pytest.mark.asyncio
async def test_mib_report_includes_country_and_class_counts(db_session: AsyncSession) -> None:
    bundle = parse_mib_file(FIXTURE)
    await import_muslimsinbritain_bundle(
        db_session,
        bundle,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    report = await build_coverage_report(db_session)
    assert report.source_count == 3
    assert report.country_counts["GB"] == 2
    assert report.country_counts["IE"] == 1
    assert report.record_class_counts["mosque"] == 2
    assert report.record_class_counts["uncertain"] == 1
