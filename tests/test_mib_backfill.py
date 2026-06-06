"""Tests for the MiB website backfill (services.mib_backfill)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.ingest.sources.muslimsinbritain import (
    import_muslimsinbritain_bundle,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import (
    MibImportBundle,
    MibMosqueRecord,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource
from uk_jamaat_directory.services.mib_backfill import (
    MibWebsiteBackfillResult,
    backfill_mib_websites,
)


def _make_mosque(
    *,
    name: str,
    postcode: str,
    website_url: str | None = None,
    latitude: float = 51.5,
    longitude: float = -0.1,
) -> Mosque:
    mosque = Mosque(
        name=name,
        normalized_name=normalize_mosque_name(name),
        city="London",
        postcode=postcode,
        country="GB",
        website_url=website_url,
    )
    set_mosque_point(mosque, latitude, longitude)
    return mosque


def _bundle_with_website(
    *,
    external_id: str = "mib-website-test-001",
    website_url: str | None = "https://mib.example.org",
    name: str = "Test Mosque",
    postcode: str = "E1 1AA",
    latitude: float = 51.5,
    longitude: float = -0.1,
) -> MibImportBundle:
    return MibImportBundle(
        exported_at=None,
        attribution="MuslimsInBritain.org",
        mosques=[
            MibMosqueRecord(
                external_id=external_id,
                name=name,
                city="London",
                postcode=postcode,
                country="GB",
                latitude=latitude,
                longitude=longitude,
                record_class="mosque",
                website_url=website_url,
            )
        ],
    )


async def _import_source(
    session: AsyncSession,
    *,
    external_id: str = "mib-website-test-001",
    website_url: str | None = "https://mib.example.org",
    name: str = "Test Mosque",
    postcode: str = "E1 1AA",
    latitude: float = 51.5,
    longitude: float = -0.1,
) -> MosqueSource:
    await import_muslimsinbritain_bundle(
        session,
        _bundle_with_website(
            external_id=external_id,
            website_url=website_url,
            name=name,
            postcode=postcode,
            latitude=latitude,
            longitude=longitude,
        ),
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await session.commit()
    return (
        await session.scalars(select(MosqueSource).where(MosqueSource.external_id == external_id))
    ).one()


@pytest.mark.asyncio
async def test_backfill_updates_empty_website_from_mib(db_session: AsyncSession) -> None:
    mosque = _make_mosque(name="Pre-existing OSM Masjid", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    source = await _import_source(
        db_session,
        name="Pre-existing OSM Masjid",
        postcode="E1 1AA",
    )
    assert source.mosque_id == mosque.id
    assert source.metadata_["website_url"] == "https://mib.example.org"
    assert mosque.website_url is None

    result = await backfill_mib_websites(db_session, dry_run=False)
    await db_session.commit()
    await db_session.refresh(mosque)

    assert isinstance(result, MibWebsiteBackfillResult)
    assert result.candidates == 1
    assert result.updated == 1
    assert result.skipped_already_set == 0
    assert result.skipped_no_mosque == 0
    assert result.skipped_no_website_in_metadata == 0
    assert result.errors == []
    assert mosque.website_url == "https://mib.example.org"


@pytest.mark.asyncio
async def test_backfill_does_not_overwrite_existing_website(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque(
        name="OSM Masjid with site",
        postcode="E1 2BB",
        website_url="https://canonical.example.org",
    )
    db_session.add(mosque)
    await db_session.commit()

    await _import_source(
        db_session,
        name="OSM Masjid with site",
        postcode="E1 2BB",
    )

    result = await backfill_mib_websites(db_session, dry_run=False)
    await db_session.commit()
    await db_session.refresh(mosque)

    assert result.candidates == 1
    assert result.updated == 0
    assert result.skipped_already_set == 1
    assert mosque.website_url == "https://canonical.example.org"


@pytest.mark.asyncio
async def test_backfill_skips_mib_source_without_website(
    db_session: AsyncSession,
) -> None:
    await _import_source(db_session, website_url=None)

    result = await backfill_mib_websites(db_session, dry_run=False)
    assert result.candidates == 0
    assert result.updated == 0


@pytest.mark.asyncio
async def test_backfill_dry_run_makes_no_changes(db_session: AsyncSession) -> None:
    mosque = _make_mosque(name="Dry Run Masjid", postcode="E1 4DD")
    db_session.add(mosque)
    await db_session.commit()

    await _import_source(
        db_session,
        name="Dry Run Masjid",
        postcode="E1 4DD",
    )

    result = await backfill_mib_websites(db_session, dry_run=True)
    await db_session.refresh(mosque)

    assert result.candidates == 1
    assert result.updated == 1
    assert mosque.website_url is None


@pytest.mark.asyncio
async def test_backfill_skips_unlinked_mib_source(db_session: AsyncSession) -> None:
    """An MiB source whose mosque_id is None must be counted as skipped, not crash."""
    source = await _import_source(db_session)
    source.mosque_id = None
    await db_session.commit()

    result = await backfill_mib_websites(db_session, dry_run=False)
    assert result.candidates == 1
    assert result.updated == 0
    assert result.skipped_no_mosque == 1


@pytest.mark.asyncio
async def test_backfill_result_as_dict_shape(db_session: AsyncSession) -> None:
    """MibWebsiteBackfillResult.as_dict() must be JSON-serialisable for CLI output."""
    result = MibWebsiteBackfillResult()
    result.candidates = 5
    result.updated = 3
    result.skipped_already_set = 1
    result.skipped_no_mosque = 1
    result.skipped_no_website_in_metadata = 0
    result.errors = ["boom"]

    blob = result.as_dict()
    assert blob == {
        "candidates": 5,
        "updated": 3,
        "skipped_already_set": 1,
        "skipped_no_mosque": 1,
        "skipped_no_website_in_metadata": 0,
        "errors": ["boom"],
    }


@pytest.mark.asyncio
async def test_backfill_only_mib_sources_are_considered(
    db_session: AsyncSession,
) -> None:
    """OSM sources with website_url must not be picked up by the backfill."""
    db_session.add(
        MosqueSource(
            source_type=SourceType.OPENSTREETMAP,
            external_id="osm-website-1",
            mosque_id=None,
            metadata_={"website_url": "https://osm.example.org"},
        )
    )
    await db_session.commit()

    result = await backfill_mib_websites(db_session, dry_run=False)
    assert result.candidates == 0
    assert result.updated == 0
