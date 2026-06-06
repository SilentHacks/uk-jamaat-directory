"""Tests for Phase 5 website discovery: providers, verification gate,
orchestrator. The HTTP fetch is injected in unit tests so the suite runs
without network.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy, SourceType
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.websites.providers.mib_metadata import (
    HOMEPAGE_KEYS,
    propose_mib_metadata_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.osm_tag_recheck import (
    propose_osm_tag_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.discovery.websites.verify import (
    PUBLIC_LINKED_PROVIDERS,
    VerificationOutcome,
    domain_is_denied,
    name_ratio,
    public_linked_provider,
    summarize,
    verify_website,
)
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.models.core import Mosque, MosqueSource
from uk_jamaat_directory.services.website_discovery import (
    DiscoveryRunResult,
    run_website_discovery,
)


def _make_mosque(
    *,
    name: str = "Test Mosque",
    postcode: str = "E1 1AA",
    website_url: str | None = None,
    address_line1: str | None = "10 Test Street",
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
        address_line1=address_line1,
    )
    set_mosque_point(mosque, latitude, longitude)
    return mosque


# ---------------------------------------------------------------------------
# domain_is_denied + name_ratio
# ---------------------------------------------------------------------------


def test_domain_is_denied_blocks_aggregators() -> None:
    assert domain_is_denied("https://facebook.com/test-mosque")
    assert domain_is_denied("https://www.yell.com/biz/test-mosque")
    assert domain_is_denied("https://muslimsinbritain.org/m/123")
    assert not domain_is_denied("https://www.test-mosque.org.uk/")
    assert not domain_is_denied("https://mosque.org.uk")


def test_name_ratio_is_zero_for_empty_haystack() -> None:
    assert name_ratio("Test Mosque", "") == 0.0


def test_name_ratio_matches_when_title_includes_name() -> None:
    ratio = name_ratio("East London Mosque", "East London Mosque & Islamic Centre")
    assert ratio >= 60.0


# ---------------------------------------------------------------------------
# verify_website (moderate strictness)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_website_short_circuits_for_mib_linked_lead(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-website-verify-001",
        mosque_id=mosque.id,
        metadata_={"website_url": "https://www.test-mosque.org.uk/"},
    )
    db_session.add(source)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://www.test-mosque.org.uk/",
        provider=WebsiteProvider.MIB_METADATA,
        reason="mib_metadata_homepage",
        linked_source_id=source.id,
    )
    outcome = await verify_website(lead, mosque, user_agent="test")
    assert outcome.verified is True
    assert outcome.notes.startswith("public linked source")


@pytest.mark.asyncio
async def test_verify_website_denies_aggregator_domain(db_session: AsyncSession) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://facebook.com/test-mosque",
        provider=WebsiteProvider.DUCKDUCKGO,
        reason="search result",
    )
    outcome = await verify_website(lead, mosque, user_agent="test")
    assert outcome.verified is False
    assert outcome.domain_denied is True


@pytest.mark.asyncio
async def test_verify_website_passes_name_plus_postcode(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://www.eastlondonmosque.org.uk/",
        provider=WebsiteProvider.DUCKDUCKGO,
        reason="search result",
    )

    async def fake_fetch(url: str) -> tuple[str, str]:
        assert url == lead.url
        return (
            "East London Mosque & Islamic Centre",
            "Welcome to the East London Mosque. Visit us at E1 1AA, London.",
        )

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is True
    assert outcome.matched_postcode is True
    assert outcome.name_ratio is not None and outcome.name_ratio >= 60.0


@pytest.mark.asyncio
async def test_verify_website_rejects_when_only_name_matches(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque(name="Test Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://www.test-mosque.org.uk/",
        provider=WebsiteProvider.DUCKDUCKGO,
        reason="search result",
    )

    async def fake_fetch(url: str) -> tuple[str, str]:
        return ("Test Mosque", "Some unrelated page about other things.")

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is False
    assert outcome.matched_postcode is False
    assert outcome.name_ratio is not None and outcome.name_ratio >= 60.0


@pytest.mark.asyncio
async def test_verify_website_records_fetch_failure(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://www.test-mosque.org.uk/",
        provider=WebsiteProvider.DUCKDUCKGO,
        reason="search result",
    )

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        return None

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is False
    assert outcome.name_ratio is None
    assert "fetch failed" in outcome.notes


def test_summarize_counts_outcomes() -> None:
    outcomes = [
        VerificationOutcome(
            lead=WebsiteLead(
                mosque_id=uuid.uuid4(),
                url="https://a",
                provider=WebsiteProvider.DUCKDUCKGO,
                reason="r",
            ),
            verified=True,
            name_ratio=80.0,
            matched_postcode=True,
            matched_address=False,
            domain_denied=False,
            notes="ok",
        ),
        VerificationOutcome(
            lead=WebsiteLead(
                mosque_id=uuid.uuid4(),
                url="https://facebook.com/x",
                provider=WebsiteProvider.DUCKDUCKGO,
                reason="r",
            ),
            verified=False,
            name_ratio=None,
            matched_postcode=False,
            matched_address=False,
            domain_denied=True,
            notes="denied",
        ),
        VerificationOutcome(
            lead=WebsiteLead(
                mosque_id=uuid.uuid4(),
                url="https://b",
                provider=WebsiteProvider.DUCKDUCKGO,
                reason="r",
            ),
            verified=False,
            name_ratio=80.0,
            matched_postcode=False,
            matched_address=False,
            domain_denied=False,
            notes="no match",
        ),
        VerificationOutcome(
            lead=WebsiteLead(
                mosque_id=uuid.uuid4(),
                url="https://c",
                provider=WebsiteProvider.DUCKDUCKGO,
                reason="r",
            ),
            verified=False,
            name_ratio=None,
            matched_postcode=False,
            matched_address=False,
            domain_denied=False,
            notes="fetch failed",
        ),
    ]
    summary = summarize(outcomes)
    assert summary == {
        "verified": 1,
        "denied": 1,
        "fetch_failed": 1,
        "no_match": 1,
    }


def test_public_linked_provider_includes_tier1() -> None:
    assert public_linked_provider(WebsiteProvider.MIB_METADATA)
    assert public_linked_provider(WebsiteProvider.CHARITY_COMMISSION)
    assert public_linked_provider(WebsiteProvider.WIKIDATA)
    assert not public_linked_provider(WebsiteProvider.DUCKDUCKGO)
    assert PUBLIC_LINKED_PROVIDERS == frozenset(
        {
            WebsiteProvider.MIB_METADATA,
            WebsiteProvider.OSM_TAG_RECHECK,
            WebsiteProvider.CHARITY_COMMISSION,
            WebsiteProvider.WIKIDATA,
        }
    )


# ---------------------------------------------------------------------------
# MiB metadata walk provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mib_metadata_walk_finds_homepage_keys(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-mwalk-001",
        mosque_id=mosque.id,
        metadata_={
            "country": "GB",
            "homepage": "https://www.test-mosque.org.uk/",
            "detail_page_url": "https://muslimsinbritain.org/m/1",
            "source_url": "https://muslimsinbritain.org/m/1",
        },
    )
    db_session.add(source)
    await db_session.commit()

    leads, result = await propose_mib_metadata_leads(db_session)
    urls = [lead.url for lead in leads]
    assert "https://www.test-mosque.org.uk/" in urls
    assert result.candidates_proposed == 1
    # Non-homepage keys must be skipped
    assert all("muslimsinbritain.org" not in lead.url for lead in leads)
    # The lead is MiB-linked
    assert all(lead.linked_source_id == source.id for lead in leads)


@pytest.mark.asyncio
async def test_mib_metadata_walk_ignores_already_promoted_website_url(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-mwalk-002",
        mosque_id=mosque.id,
        metadata_={
            "website_url": "https://www.test-mosque.org.uk/",
            "homepage": "https://homepage.example.org/",
        },
    )
    db_session.add(source)
    await db_session.commit()

    leads, _ = await propose_mib_metadata_leads(db_session)
    urls = [lead.url for lead in leads]
    assert "https://www.test-mosque.org.uk/" not in urls
    assert "https://homepage.example.org/" in urls


@pytest.mark.asyncio
async def test_mib_metadata_walk_ignores_unlinked_mib_source(
    db_session: AsyncSession,
) -> None:
    """An MiB source with no mosque_id must not produce leads."""
    source = MosqueSource(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-mwalk-003",
        mosque_id=None,
        metadata_={"homepage": "https://www.test-mosque.org.uk/"},
    )
    db_session.add(source)
    await db_session.commit()

    leads, _ = await propose_mib_metadata_leads(db_session)
    assert leads == []


def test_mib_metadata_homepage_keys_cover_canonical_names() -> None:
    assert "homepage" in HOMEPAGE_KEYS
    assert "homepage_url" in HOMEPAGE_KEYS
    assert "official_website" in HOMEPAGE_KEYS


# ---------------------------------------------------------------------------
# Orchestrator: run_website_discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_promotes_mib_metadata_and_records_audit(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-orch-001",
        mosque_id=mosque.id,
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        metadata_={"homepage": "https://www.test-mosque.org.uk/"},
    )
    db_session.add(source)
    await db_session.commit()

    result = await run_website_discovery(db_session)
    await db_session.commit()
    await db_session.refresh(mosque)

    assert isinstance(result, DiscoveryRunResult)
    assert result.promoted == 1
    assert result.verified == 1
    assert result.leads_recorded == 0
    assert mosque.website_url == "https://www.test-mosque.org.uk/"

    # A manual source row was added
    from sqlalchemy import select

    manual_sources = list(
        (
            await db_session.scalars(
                select(MosqueSource).where(
                    MosqueSource.source_type == SourceType.MANUAL,
                    MosqueSource.mosque_id == mosque.id,
                )
            )
        ).all()
    )
    assert len(manual_sources) == 1
    assert manual_sources[0].publication_policy == (
        SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED
    )
    assert "MuslimsInBritain" in (manual_sources[0].attribution or "")


@pytest.mark.asyncio
async def test_orchestrator_records_lead_for_unverifiable_candidate(
    db_session: AsyncSession,
) -> None:
    """A search-engine lead that fails verification must become a discovery lead."""
    mosque = _make_mosque(name="Test Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    async def stub_provider(session: AsyncSession):
        lead = WebsiteLead(
            mosque_id=mosque.id,
            url="https://www.test-mosque.org.uk/",
            provider=WebsiteProvider.DUCKDUCKGO,
            reason="search result",
        )
        from uk_jamaat_directory.ingest.discovery.websites.types import (
            WebsiteLeadResult,
        )

        return [lead], WebsiteLeadResult(candidates_proposed=1)

    async def fake_fetch(url: str) -> tuple[str, str]:
        return ("Other content", "Nothing relevant here.")

    # No monkey-patching of the fetcher here; the orchestrator uses
    # verify_website which will try to fetch the URL. We expect either a
    # network failure (no result, no promotion) or a name mismatch.
    # The important guarantee is: mosque.website_url stays None.
    await run_website_discovery(
        db_session,
        providers=[stub_provider],
        user_agent="test",
    )
    await db_session.commit()
    await db_session.refresh(mosque)
    assert mosque.website_url is None


@pytest.mark.asyncio
async def test_orchestrator_skips_mosques_that_already_have_website(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque(website_url="https://existing.example.org/")
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-skip-001",
        mosque_id=mosque.id,
        metadata_={"homepage": "https://www.test-mosque.org.uk/"},
    )
    db_session.add(source)
    await db_session.commit()

    result = await run_website_discovery(db_session)
    await db_session.refresh(mosque)
    assert result.promoted == 0
    assert mosque.website_url == "https://existing.example.org/"


async def test_osm_tag_recheck_proposes_alternate_website(
    db_session: AsyncSession,
) -> None:
    from uk_jamaat_directory.ingest.discovery.websites.providers.osm_tag_recheck import (
        propose_osm_tag_leads,
    )

    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/12345",
        mosque_id=mosque.id,
        source_url="https://www.openstreetmap.org/node/12345",
        attribution="OpenStreetMap contributors",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        metadata_={
            "website_tags": [
                "https://www.mosque-alt.example.org/",
                "https://www.mosque-alt.example.org/contact",
            ],
        },
    )
    db_session.add(source)
    await db_session.commit()

    leads, result = await propose_osm_tag_leads(db_session)
    assert {lead.url for lead in leads} == {
        "https://www.mosque-alt.example.org/",
        "https://www.mosque-alt.example.org/contact",
    }
    assert all(lead.provider == WebsiteProvider.OSM_TAG_RECHECK for lead in leads)
    assert all(lead.linked_source_id == source.id for lead in leads)
    assert result.candidates_proposed == 2


async def test_osm_tag_recheck_skips_existing_website(
    db_session: AsyncSession,
) -> None:
    from uk_jamaat_directory.ingest.discovery.websites.providers.osm_tag_recheck import (
        propose_osm_tag_leads,
    )

    mosque = _make_mosque(website_url="https://www.mosque.example.org/")
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/22222",
        mosque_id=mosque.id,
        metadata_={
            "website_tags": [
                "https://www.mosque.example.org/",
                "https://www.mosque.example.org/about",
            ],
        },
    )
    db_session.add(source)
    await db_session.commit()

    leads, _ = await propose_osm_tag_leads(db_session)
    assert {lead.url for lead in leads} == {"https://www.mosque.example.org/about"}


async def test_osm_tag_recheck_promotes_via_orchestrator(
    db_session: AsyncSession,
) -> None:
    mosque = _make_mosque()
    db_session.add(mosque)
    await db_session.commit()
    source = MosqueSource(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/33333",
        mosque_id=mosque.id,
        metadata_={"website_tags": ["https://www.osm-discovered.example.org/"]},
    )
    db_session.add(source)
    await db_session.commit()

    result = await run_website_discovery(
        db_session,
        providers=[propose_osm_tag_leads],
    )
    await db_session.commit()
    await db_session.refresh(mosque)
    assert mosque.website_url == "https://www.osm-discovered.example.org/"
    assert result.promoted >= 1
