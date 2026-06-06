"""Tests for the OSCR (Office of the Scottish Charity Regulator) bulk-register
website discovery provider.

Mirrors :mod:`tests.test_charity_commission_discovery` but uses the OSCR
CSV header / quoting convention and the OSCR enum / source type.
"""

from __future__ import annotations

import csv
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.websites.providers.charity_index import (
    load_oscr_index,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.oscr import (
    propose_oscr_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.types import WebsiteProvider
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.models.core import Mosque, MosqueSource


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "Charity Number",
        "Charity Name",
        "Charity Status",
        "Postcode",
        "Website",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=",", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_mosque(
    *,
    name: str = "Test Mosque",
    postcode: str = "G1 1AA",
    website_url: str | None = None,
    latitude: float = 55.86,
    longitude: float = -4.25,
) -> Mosque:
    mosque = Mosque(
        name=name,
        normalized_name=normalize_mosque_name(name),
        city="Glasgow",
        postcode=postcode,
        country="GB",
        website_url=website_url,
    )
    set_mosque_point(mosque, latitude, longitude)
    return mosque


@pytest.fixture
def oscr_csv(tmp_path: Path) -> Path:
    path = tmp_path / "charity.csv"
    _write_csv(
        path,
        [
            {
                "Charity Number": "SC000001",
                "Charity Name": "Glasgow Central Mosque",
                "Charity Status": "Active",
                "Postcode": "G1 1AA",
                "Website": "www.glasgowcentralmosque.org",
            },
            {
                "Charity Number": "SC000002",
                "Charity Name": "Edinburgh Central Mosque Trust",
                "Charity Status": "Active",
                "Postcode": "EH8 9BT",
                "Website": "https://edinburghcentralmosque.org",
            },
            {
                "Charity Number": "SC000003",
                "Charity Name": "Scottish Muslim Unrelated Charity",
                "Charity Status": "Active",
                "Postcode": "G1 1AA",
                "Website": "www.unrelated-charity.example.org",
            },
        ],
    )
    return path


async def test_load_oscr_index_postcode_keys(oscr_csv: Path) -> None:
    index = load_oscr_index(oscr_csv)
    assert "G11AA" in index
    assert "EH89BT" in index
    assert len(index["G11AA"]) == 2


async def test_propose_oscr_leads_matches_by_name_and_postcode(
    db_session: AsyncSession, oscr_csv: Path
) -> None:
    mosque = _make_mosque(name="Glasgow Central Mosque & Islamic Centre", postcode="G1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    index = load_oscr_index(oscr_csv)
    leads, result = await propose_oscr_leads(db_session, charity_index=index)
    assert result.candidates_proposed == 1
    assert len(leads) == 1
    lead = leads[0]
    assert lead.provider == WebsiteProvider.OSCR
    assert lead.url == "https://www.glasgowcentralmosque.org"
    assert lead.matched_postcode == "G1 1AA"
    assert lead.extra["charity_number"] == "SC000001"


async def test_propose_oscr_leads_writes_oscr_source_row(
    db_session: AsyncSession, oscr_csv: Path
) -> None:
    from sqlalchemy import select

    mosque = _make_mosque(name="Glasgow Central Mosque", postcode="G1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    index = load_oscr_index(oscr_csv)
    leads, _ = await propose_oscr_leads(db_session, charity_index=index)
    await db_session.flush()

    rows = list(
        (
            await db_session.execute(
                select(MosqueSource).where(MosqueSource.source_type == SourceType.OSCR_REGISTER)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].external_id == "SC000001"
    assert leads[0].linked_source_id == rows[0].id


async def test_propose_oscr_leads_reuses_existing_source(
    db_session: AsyncSession, oscr_csv: Path
) -> None:
    mosque = _make_mosque(name="Glasgow Central Mosque", postcode="G1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    prior = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.OSCR_REGISTER,
        external_id="SC000001",
        source_url="https://www.glasgowcentralmosque.org",
        display_name="Glasgow Central Mosque",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        attribution="Office of the Scottish Charity Regulator (Open Government Licence v3.0)",
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(prior)
    await db_session.commit()

    index = load_oscr_index(oscr_csv)
    leads, _ = await propose_oscr_leads(db_session, charity_index=index)
    assert leads[0].linked_source_id == prior.id


async def test_propose_oscr_leads_already_have_website(
    db_session: AsyncSession, oscr_csv: Path
) -> None:
    mosque = _make_mosque(
        name="Glasgow Central Mosque",
        postcode="G1 1AA",
        website_url="https://www.glasgowcentralmosque.org",
    )
    db_session.add(mosque)
    await db_session.commit()

    index = load_oscr_index(oscr_csv)
    leads, result = await propose_oscr_leads(db_session, charity_index=index)
    assert leads == []
    assert result.candidates_proposed == 0


async def test_propose_oscr_leads_rejects_single_token_overlap(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    path = tmp_path / "charity.csv"
    _write_csv(
        path,
        [
            {
                "Charity Number": "SC009999",
                "Charity Name": "Space @The Broomhouse Hub",
                "Charity Status": "Active",
                "Postcode": "EH11 3RH",
                "Website": "www.spacescot.org",
            },
        ],
    )
    mosque = _make_mosque(name="Broomhouse Mosque", postcode="EH11 3RH")
    db_session.add(mosque)
    await db_session.commit()

    index = load_oscr_index(path)
    leads, result = await propose_oscr_leads(db_session, charity_index=index)
    assert leads == []
    assert result.candidates_proposed == 0


async def test_propose_oscr_leads_promotes_via_orchestrator(
    db_session: AsyncSession, oscr_csv: Path
) -> None:
    from uk_jamaat_directory.services.website_discovery import (
        run_website_discovery,
    )

    mosque = _make_mosque(name="Edinburgh Central Mosque Trust", postcode="EH8 9BT")
    db_session.add(mosque)
    await db_session.commit()

    index = load_oscr_index(oscr_csv)

    async def _with_index(session):
        return await propose_oscr_leads(session, charity_index=index)

    result = await run_website_discovery(db_session, providers=[_with_index])
    await db_session.commit()
    await db_session.refresh(mosque)
    assert mosque.website_url == "https://edinburghcentralmosque.org"
    assert result.promoted == 1
