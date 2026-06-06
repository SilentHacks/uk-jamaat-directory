"""Tests for the Charity Commission bulk-register website discovery provider.

The Charity Commission for England and Wales publishes a daily TSV extract
of every registered charity under the Open Government Licence v3.0. The
``propose_charity_commission_leads`` provider loads that extract, joins on
postcode + fuzzy name match against mosques missing a website, writes a
synthetic ``SourceType.CHARITY_REGISTER`` source row per match, and
proposes a lead flagged with ``linked_source_id``.

These tests build a tiny TSV in a temp dir (no real CC data) and exercise
the match, the upsert, and the orchestrator integration.
"""

from __future__ import annotations

import csv
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.websites.providers.charity_commission import (
    propose_charity_commission_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.charity_index import (
    load_charity_index,
)
from uk_jamaat_directory.ingest.discovery.websites.types import WebsiteProvider
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.models.core import Mosque


def _write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "registered_charity_number",
        "charity_name",
        "charity_registration_status",
        "charity_contact_postcode",
        "charity_contact_web",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _make_mosque(
    *,
    name: str = "Test Mosque",
    postcode: str = "E1 1AA",
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


@pytest.fixture
def charity_tsv(tmp_path: Path) -> Path:
    path = tmp_path / "charity.tsv"
    _write_tsv(
        path,
        [
            {
                "registered_charity_number": "100100",
                "charity_name": "East London Mosque Trust",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "E1 1AA",
                "charity_contact_web": "www.eastlondonmosque.org.uk",
            },
            {
                "registered_charity_number": "100101",
                "charity_name": "Bradford Central Mosque",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "BD1 1AA",
                "charity_contact_web": "https://bradfordmosque.org",
            },
            {
                "registered_charity_number": "100102",
                "charity_name": "Unrelated Charity",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "E1 1AA",
                "charity_contact_web": "www.unrelated-charity.example.org",
            },
            {
                "registered_charity_number": "100103",
                "charity_name": "Denied Charity",
                "charity_registration_status": "Registered",
                "charity_contact_postcode": "E1 1AA",
                "charity_contact_web": "https://facebook.com/page",
            },
        ],
    )
    return path


async def test_load_charity_index_postcode_keys(charity_tsv: Path) -> None:
    index = load_charity_index(charity_tsv)
    assert "E11AA" in index
    assert "BD11AA" in index
    assert len(index["E11AA"]) == 3
    assert {c.charity_number for c in index["E11AA"]} == {
        "100100",
        "100102",
        "100103",
    }


async def test_propose_charity_commission_leads_matches_by_name_and_postcode(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    mosque = _make_mosque(name="East London Mosque & Islamic Centre", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    index = load_charity_index(charity_tsv)
    leads, result = await propose_charity_commission_leads(db_session, charity_index=index)
    assert result.candidates_proposed == 1
    assert len(leads) == 1
    lead = leads[0]
    assert lead.provider == WebsiteProvider.CHARITY_COMMISSION
    assert lead.url == "https://www.eastlondonmosque.org.uk"
    assert lead.matched_postcode == "E1 1AA"
    assert lead.extra["charity_number"] == "100100"


async def test_propose_charity_commission_leads_skips_deny_list(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    mosque = _make_mosque(
        name="East London Mosque Trust", postcode="E1 1AA"
    )
    db_session.add(mosque)
    await db_session.commit()

    index = load_charity_index(charity_tsv)
    leads, _ = await propose_charity_commission_leads(
        db_session, charity_index=index
    )
    # Two charities match the postcode + "East London Mosque Trust" name.
    # One (charity 100103) is on the deny-list (facebook.com), so only the
    # other should be proposed.
    urls = {lead.url for lead in leads}
    assert urls == {"https://www.eastlondonmosque.org.uk"}


async def test_propose_charity_commission_leads_writes_source_row(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    from sqlalchemy import select

    from uk_jamaat_directory.models.core import MosqueSource

    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    index = load_charity_index(charity_tsv)
    leads, _ = await propose_charity_commission_leads(db_session, charity_index=index)
    await db_session.flush()

    rows = list(
        (
            await db_session.execute(
                select(MosqueSource).where(MosqueSource.source_type == SourceType.CHARITY_REGISTER)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].external_id == "100100"
    assert rows[0].mosque_id == mosque.id
    assert leads[0].linked_source_id == rows[0].id


async def test_propose_charity_commission_leads_reuses_existing_source(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    from datetime import UTC, datetime

    from uk_jamaat_directory.domain import (
        Confidence,
        SourcePublicationPolicy,
    )
    from uk_jamaat_directory.models.core import MosqueSource

    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    prior = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.CHARITY_REGISTER,
        external_id="100100",
        source_url="https://www.eastlondonmosque.org.uk",
        display_name="East London Mosque Trust",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        attribution="Charity Commission for England and Wales (Open Government Licence v3.0)",
        last_seen_at=datetime.now(UTC),
    )
    db_session.add(prior)
    await db_session.commit()

    index = load_charity_index(charity_tsv)
    leads, _ = await propose_charity_commission_leads(db_session, charity_index=index)
    assert leads[0].linked_source_id == prior.id


async def test_propose_charity_commission_leads_no_postcode_skipped(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    mosque = _make_mosque(name="No-Postcode Mosque", postcode=None)
    db_session.add(mosque)
    await db_session.commit()

    index = load_charity_index(charity_tsv)
    leads, result = await propose_charity_commission_leads(db_session, charity_index=index)
    assert leads == []
    assert result.candidates_proposed == 0


async def test_propose_charity_commission_leads_already_have_website(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    mosque = _make_mosque(
        name="East London Mosque",
        postcode="E1 1AA",
        website_url="https://www.eastlondonmosque.org.uk",
    )
    db_session.add(mosque)
    await db_session.commit()

    index = load_charity_index(charity_tsv)
    leads, result = await propose_charity_commission_leads(db_session, charity_index=index)
    assert leads == []
    assert result.candidates_proposed == 0


async def test_propose_charity_commission_leads_promotes_via_orchestrator(
    db_session: AsyncSession, charity_tsv: Path
) -> None:
    from uk_jamaat_directory.services.website_discovery import (
        run_website_discovery,
    )

    mosque = _make_mosque(name="Bradford Central Mosque", postcode="BD1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    index = load_charity_index(charity_tsv)

    async def _with_index(session):
        return await propose_charity_commission_leads(session, charity_index=index)

    result = await run_website_discovery(db_session, providers=[_with_index])
    await db_session.commit()
    await db_session.refresh(mosque)
    assert mosque.website_url == "https://bradfordmosque.org"
    assert result.promoted == 1
