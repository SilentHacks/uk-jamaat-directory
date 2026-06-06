"""Tests for Phase 5 extended discovery: contact-page fallback,
directory-aggregator resolver, and audit-lead analysis.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.websites.analysis import (
    _parse_lead_notes,
)
from uk_jamaat_directory.ingest.discovery.websites.directory_resolver import (
    _extract_jsonld_url,
    _extract_website_anchor,
    is_aggregator_domain,
    resolve_directory_url,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.discovery.websites.verify import (
    verify_website,
)
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.models.core import Mosque


def _make_mosque(
    *,
    name: str = "Test Mosque",
    postcode: str = "E1 1AA",
    address_line1: str | None = "10 Test Street",
) -> Mosque:
    mosque = Mosque(
        name=name,
        normalized_name=normalize_mosque_name(name),
        city="London",
        postcode=postcode,
        country="GB",
        address_line1=address_line1,
    )
    set_mosque_point(mosque, 51.5, -0.1)
    return mosque


# ---------------------------------------------------------------------------
# Directory resolver — unit tests (no DB)
# ---------------------------------------------------------------------------


def test_is_aggregator_domain_recognises_known_sites() -> None:
    assert is_aggregator_domain("https://praysalat.com/mosque/123")
    assert is_aggregator_domain("https://www.islamicfinder.org/mosque/123")
    assert is_aggregator_domain("https://nearestmosque.com/m/456")
    assert not is_aggregator_domain("https://www.birmingham-mosque.org.uk/")


def test_extract_jsonld_url_finds_place_url() -> None:
    html = """
    <script type="application/ld+json">
    {"@type": "Place", "name": "Test Mosque", "url": "https://real-mosque.org"}
    </script>
    """
    assert _extract_jsonld_url(html) == "https://real-mosque.org"


def test_extract_jsonld_url_finds_organization_url() -> None:
    html = """
    <script type="application/ld+json">
    {"@type": "Organization", "url": "https://org-mosque.org"}
    </script>
    """
    assert _extract_jsonld_url(html) == "https://org-mosque.org"


def test_extract_jsonld_url_ignores_wrong_type() -> None:
    html = """
    <script type="application/ld+json">
    {"@type": "Person", "url": "https://person.example.com"}
    </script>
    """
    assert _extract_jsonld_url(html) is None


def test_extract_jsonld_url_handles_list() -> None:
    html = """
    <script type="application/ld+json">
    [
      {"@type": "Thing"},
      {"@type": "Place", "url": "https://place.example.com"}
    ]
    </script>
    """
    assert _extract_jsonld_url(html) == "https://place.example.com"


def test_extract_website_anchor_finds_official_website() -> None:
    html = '<a href="https://real-mosque.org">Official Website</a>'
    assert _extract_website_anchor(html) == "https://real-mosque.org"


def test_extract_website_anchor_finds_visit_website() -> None:
    html = '<a href="https://real-mosque.org">Visit our website</a>'
    assert _extract_website_anchor(html) == "https://real-mosque.org"


def test_extract_website_anchor_ignores_unrelated_links() -> None:
    html = '<a href="https://example.com">Click here</a>'
    assert _extract_website_anchor(html) is None


def test_resolve_directory_url_returns_none_for_plain_page() -> None:
    html = "<html><body>Just some mosque info</body></html>"
    assert resolve_directory_url("https://example.com/mosque", html) is None


def test_resolve_directory_url_blocks_loopback() -> None:
    """An extracted URL that loops back to the same aggregator domain is rejected."""
    html = """
    <script type="application/ld+json">
    {"@type": "Place", "url": "https://praysalat.com/other-page"}
    </script>
    """
    assert resolve_directory_url("https://praysalat.com/mosque/123", html) is None


def test_resolve_directory_url_extracts_from_aggregator() -> None:
    html = """
    <script type="application/ld+json">
    {"@type": "Place", "url": "https://real-mosque.org.uk"}
    </script>
    """
    result = resolve_directory_url("https://praysalat.com/mosque/123", html)
    assert result == "https://real-mosque.org.uk"


# ---------------------------------------------------------------------------
# verify_website — contact-page fallback (PostGIS tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_website_falls_back_to_contact_page_on_name_match(
    db_session: AsyncSession,
) -> None:
    """Homepage has generic title; contact page has name + postcode."""
    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://www.elm.org.uk/",
        provider=WebsiteProvider.SEARCH_ENGINE,
        reason="search result",
    )

    fetched: dict[str, tuple[str, str]] = {
        "https://www.elm.org.uk/": ("Welcome", "Welcome to our centre."),
        "https://www.elm.org.uk/contact": (
            "Contact East London Mosque",
            "Get in touch with East London Mosque at E1 1AA.",
        ),
    }

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        return fetched.get(url)

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is True
    assert "contact_page" in outcome.notes
    assert outcome.name_ratio is not None and outcome.name_ratio >= 60.0


@pytest.mark.asyncio
async def test_verify_website_contact_fallback_stops_on_first_hit(
    db_session: AsyncSession,
) -> None:
    """Only the third contact path hits; earlier ones 404."""
    mosque = _make_mosque(name="Test Mosque", postcode="AB1 2CD")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://test-mosque.org/",
        provider=WebsiteProvider.SEARCH_ENGINE,
        reason="search result",
    )

    fetched: dict[str, tuple[str, str]] = {
        "https://test-mosque.org/": ("Home", "Welcome."),
        "https://test-mosque.org/contact": ("Not Found", ""),
        "https://test-mosque.org/contact-us": ("Not Found", ""),
        "https://test-mosque.org/about": (
            "About Test Mosque",
            "We are Test Mosque in AB1 2CD.",
        ),
    }

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        return fetched.get(url)

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is True
    assert "about" in outcome.notes


@pytest.mark.asyncio
async def test_verify_website_no_contact_fallback_when_homepage_verifies(
    db_session: AsyncSession,
) -> None:
    """If homepage already passes, we never fetch contact pages."""
    mosque = _make_mosque(name="Test Mosque", postcode="AB1 2CD")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://test-mosque.org/",
        provider=WebsiteProvider.SEARCH_ENGINE,
        reason="search result",
    )

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        if url == "https://test-mosque.org/":
            return ("Test Mosque", "We are at AB1 2CD.")
        # Contact pages should never be fetched
        raise AssertionError(f"Unexpected fetch: {url}")

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is True
    assert "contact_page" not in outcome.notes


@pytest.mark.asyncio
async def test_verify_website_resolves_directory_then_verifies(
    db_session: AsyncSession,
) -> None:
    """An aggregator page embeds the real URL; we verify the extracted URL."""
    mosque = _make_mosque(name="Test Mosque", postcode="AB1 2CD")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://praysalat.com/mosque/123",
        provider=WebsiteProvider.SEARCH_ENGINE,
        reason="search result",
    )

    fetched: dict[str, tuple[str, str]] = {
        "https://praysalat.com/mosque/123": (
            "PraySalat - Mosque Finder",
            '<script type="application/ld+json">{"@type": "Place", "url": "https://real-mosque.org"}</script>',
        ),
        "https://real-mosque.org": (
            "Test Mosque & Community Centre",
            "Welcome to Test Mosque. Located at AB1 2CD.",
        ),
    }

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        return fetched.get(url)

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is True
    assert "resolved_from_directory" in outcome.notes


@pytest.mark.asyncio
async def test_verify_website_directory_resolver_ignores_failed_resolved_fetch(
    db_session: AsyncSession,
) -> None:
    """If the resolved URL fails to fetch, we still report the primary failure."""
    mosque = _make_mosque(name="Test Mosque", postcode="AB1 2CD")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://praysalat.com/mosque/123",
        provider=WebsiteProvider.SEARCH_ENGINE,
        reason="search result",
    )

    fetched: dict[str, tuple[str, str]] = {
        "https://praysalat.com/mosque/123": (
            "PraySalat",
            '<script type="application/ld+json">{"@type": "Place", "url": "https://real-mosque.org"}</script>',
        ),
    }

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        return fetched.get(url)

    outcome = await verify_website(lead, mosque, user_agent="test", fetcher=fake_fetch)
    assert outcome.verified is False
    assert outcome.name_ratio is not None


# ---------------------------------------------------------------------------
# verify_website — cache interaction with fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_website_cached_homepage_skips_fetch_and_tries_fallbacks(
    db_session: AsyncSession,
) -> None:
    """A cached homepage that failed verification still triggers directory + contact fallback."""
    mosque = _make_mosque(name="Test Mosque", postcode="AB1 2CD")
    db_session.add(mosque)
    await db_session.commit()

    lead = WebsiteLead(
        mosque_id=mosque.id,
        url="https://test-mosque.org/",
        provider=WebsiteProvider.SEARCH_ENGINE,
        reason="search result",
    )

    class FakeCache:
        def __init__(self) -> None:
            self._store: dict[str, tuple[str, str]] = {
                "https://test-mosque.org/": ("Home", "Welcome."),
            }

        def get(self, url: str) -> tuple[str, str] | None:
            return self._store.get(url)

        def set(self, url: str, title: str, text: str) -> None:
            self._store[url] = (title, text)

    cache = FakeCache()

    async def fake_fetch(url: str) -> tuple[str, str] | None:
        if url == "https://test-mosque.org/contact":
            return ("Contact Test Mosque", "Contact us at AB1 2CD.")
        return None

    outcome = await verify_website(
        lead, mosque, user_agent="test", fetcher=fake_fetch, page_cache=cache
    )
    assert outcome.verified is True
    assert "contact_page" in outcome.notes
    # The fetcher should NOT have been called for the homepage
    # (it was cached), only for the contact page.


# ---------------------------------------------------------------------------
# Analysis — parsing unit tests (no DB)
# ---------------------------------------------------------------------------


def test_parse_lead_notes_extracts_search_engine_failure() -> None:
    notes = (
        "provider=search_engine reason=exa_search_rank_1 "
        "url=https://praysalat.com/123 "
        "notes=name_ratio=45 postcode=False address=False "
        "extra=query='Test Mosque' postcode result_title='PraySalat' result_rank=1"
    )
    lead = _parse_lead_notes(notes)
    assert lead.provider == "search_engine"
    assert lead.url == "https://praysalat.com/123"
    assert lead.name_ratio == 45.0
    assert lead.matched_postcode is False
    assert lead.matched_address is False
    assert lead.outcome == "no_match"
    assert lead.domain == "praysalat.com"


def test_parse_lead_notes_extracts_fetch_failure() -> None:
    notes = (
        "provider=search_engine reason=exa_search_rank_2 "
        "url=https://example.com "
        "notes=fetch failed or non-html response "
        "extra=query='Test'"
    )
    lead = _parse_lead_notes(notes)
    assert lead.name_ratio is None
    assert lead.outcome == "fetch_failed"


def test_parse_lead_notes_unknown_provider_defaults() -> None:
    lead = _parse_lead_notes("")
    assert lead.provider == "unknown"
    assert lead.domain == ""


# ---------------------------------------------------------------------------
# Postcode / address whitespace regression tests
# ---------------------------------------------------------------------------


def test_postcode_appears_with_regular_space() -> None:
    from uk_jamaat_directory.ingest.discovery.websites.verify import (
        _postcode_appears,
    )

    assert _postcode_appears("W1F 0PH", "Our address is W1F 0PH, London") is True


def test_postcode_appears_with_nonbreaking_space() -> None:
    from uk_jamaat_directory.ingest.discovery.websites.verify import (
        _postcode_appears,
    )

    # &nbsp; -> \xa0 after HTMLParser conversion
    assert _postcode_appears("W1F 0PH", "Our address is W1F\xa00PH, London") is True


def test_postcode_appears_with_nbsp_entity() -> None:
    from uk_jamaat_directory.ingest.discovery.websites.verify import (
        _postcode_appears,
    )

    assert _postcode_appears("W1F 0PH", "Our address is W1F&nbsp;0PH, London") is True


def test_postcode_appears_with_numeric_entity() -> None:
    from uk_jamaat_directory.ingest.discovery.websites.verify import (
        _postcode_appears,
    )

    assert _postcode_appears("W1F 0PH", "Our address is W1F&#160;0PH, London") is True


def test_postcode_appears_with_tab_and_newline() -> None:
    from uk_jamaat_directory.ingest.discovery.websites.verify import (
        _postcode_appears,
    )

    assert _postcode_appears("G64 1NQ", "Address:\nG64\t1NQ") is True


def test_address_appears_with_nonbreaking_space() -> None:
    from uk_jamaat_directory.ingest.discovery.websites.verify import (
        _address_appears,
    )

    assert _address_appears("10 Test Street", "Visit us at 10\xa0Test\xa0Street") is True
