"""Tests for Tier 2 search-engine website discovery (Exa client, cache, provider).

All network calls are mocked so the suite runs offline.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.websites.providers.search_engine import (
    _build_query,
    propose_search_engine_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.search.cache import SearchCache
from uk_jamaat_directory.ingest.discovery.websites.search.exa_client import (
    ExaClient,
    ExaResult,
    ExaSearchError,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.models.core import Mosque

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


class _FakeExaClient:
    """Stub Exa client that returns canned results."""

    def __init__(self, results: list[ExaResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    async def search(self, query: str, *, num_results: int = 3) -> list[ExaResult]:
        self.calls.append(query)
        return self.results

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# ExaClient unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exa_client_parses_results() -> None:
    async def _post(self_, url, *, json, **kwargs):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "results": [
                        {"title": "East London Mosque", "url": "https://www.elm.org.uk/"},
                        {"title": "Another", "url": "https://another.example/"},
                    ]
                }

        return _Resp()

    original_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _post  # type: ignore[method-assign]
    try:
        client = ExaClient(api_key="dummy")
        results = await client.search("test query")
        await client.aclose()
    finally:
        httpx.AsyncClient.post = original_post  # type: ignore[method-assign]

    assert len(results) == 2
    assert results[0].url == "https://www.elm.org.uk/"
    assert results[0].title == "East London Mosque"


@pytest.mark.asyncio
async def test_exa_client_retries_on_429() -> None:
    call_count = 0

    async def _post(self_, url, *, json, **kwargs):
        nonlocal call_count
        call_count += 1

        class _Resp:
            status_code = 429 if call_count < 3 else 200

            def raise_for_status(self):
                if self.status_code == 429:
                    raise Exception("429")

            def json(self):
                return {"results": [{"title": "OK", "url": "https://ok.example/"}]}

        return _Resp()

    original_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _post  # type: ignore[method-assign]
    try:
        client = ExaClient(api_key="dummy")
        results = await client.search("test")
        await client.aclose()
    finally:
        httpx.AsyncClient.post = original_post  # type: ignore[method-assign]

    assert call_count == 3
    assert len(results) == 1


@pytest.mark.asyncio
async def test_exa_client_raises_after_max_retries() -> None:
    async def _post(self_, url, *, json, **kwargs):
        class _Resp:
            status_code = 503

            def raise_for_status(self):
                raise Exception("503")

        return _Resp()

    original_post = httpx.AsyncClient.post
    httpx.AsyncClient.post = _post  # type: ignore[method-assign]
    try:
        client = ExaClient(api_key="dummy")
        with pytest.raises(ExaSearchError):
            await client.search("test")
        await client.aclose()
    finally:
        httpx.AsyncClient.post = original_post  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# SearchCache unit tests
# ---------------------------------------------------------------------------


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache = SearchCache(cache_file=cache_file, ttl_seconds=3600)
    results = [ExaResult(title="A Mosque", url="https://a.example/")]
    cache.set("exa", '"Test Mosque" E1 1AA', results)
    cache.commit()

    loaded = SearchCache(cache_file=cache_file, ttl_seconds=3600)
    cached = loaded.get("exa", '"Test Mosque" E1 1AA')
    assert cached is not None
    assert len(cached) == 1
    assert cached[0].url == "https://a.example/"


def test_cache_expires_after_ttl(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache = SearchCache(cache_file=cache_file, ttl_seconds=1)
    cache.set("exa", "old query", [ExaResult(title="Old", url="https://old.example/")])
    cache.commit()
    time.sleep(1.1)
    assert cache.get("exa", "old query") is None


def test_cache_set_many_and_commit(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    cache = SearchCache(cache_file=cache_file, ttl_seconds=3600)
    cache.set_many(
        "exa",
        {
            "query1": [ExaResult(title="A", url="https://a.example/")],
            "query2": [ExaResult(title="B", url="https://b.example/")],
        },
    )
    cache.commit()

    loaded = SearchCache(cache_file=cache_file, ttl_seconds=3600)
    assert loaded.get("exa", "query1") is not None
    assert loaded.get("exa", "query2") is not None


# ---------------------------------------------------------------------------
# Provider unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_proposes_leads_for_missing_website(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    fake_client = _FakeExaClient(
        [
            ExaResult(title="East London Mosque", url="https://www.elm.org.uk/"),
            ExaResult(title="ELM Location", url="https://www.elm.org.uk/location"),
        ]
    )
    cache = SearchCache(cache_file=tmp_path / "cache.json", ttl_seconds=3600)
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client, cache=cache
    )
    assert result.candidates_proposed == 2
    assert len(leads) == 2
    assert leads[0].provider == WebsiteProvider.SEARCH_ENGINE
    assert leads[0].url == "https://www.elm.org.uk/"
    assert leads[0].reason == "exa_search_rank_1"
    assert leads[0].matched_postcode == "E1 1AA"
    assert '"East London Mosque" E1 1AA' in fake_client.calls


@pytest.mark.asyncio
async def test_provider_filters_deny_list(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    mosque = _make_mosque(name="Test Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    fake_client = _FakeExaClient(
        [
            ExaResult(title="Facebook page", url="https://facebook.com/test-mosque"),
            ExaResult(title="Real site", url="https://www.test-mosque.org.uk/"),
        ]
    )
    cache = SearchCache(cache_file=tmp_path / "cache.json", ttl_seconds=3600)
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client, cache=cache
    )
    assert len(leads) == 1
    assert leads[0].url == "https://www.test-mosque.org.uk/"


@pytest.mark.asyncio
async def test_provider_uses_cache_and_skips_api(db_session: AsyncSession) -> None:
    mosque = _make_mosque(name="Cached Mosque", postcode="W1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    cache = SearchCache(cache_file=Path("/dev/null"), ttl_seconds=3600)
    cache.set(
        "exa",
        '"Cached Mosque" W1 1AA',
        [ExaResult(title="Cached", url="https://cached.example/")],
    )

    fake_client = _FakeExaClient([])
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client, cache=cache
    )
    assert len(leads) == 1
    assert leads[0].url == "https://cached.example/"
    assert fake_client.calls == []  # no API call


@pytest.mark.asyncio
async def test_provider_skips_mosques_without_postcode(db_session: AsyncSession) -> None:
    mosque = _make_mosque(name="No Postcode Mosque", postcode=None)
    db_session.add(mosque)
    await db_session.commit()

    fake_client = _FakeExaClient([ExaResult(title="X", url="https://x.example/")])
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client
    )
    assert leads == []
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_provider_skips_mosques_with_website(db_session: AsyncSession) -> None:
    mosque = _make_mosque(name="Has Website Mosque", website_url="https://existing.example/")
    db_session.add(mosque)
    await db_session.commit()

    fake_client = _FakeExaClient([ExaResult(title="X", url="https://x.example/")])
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client
    )
    assert leads == []
    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_provider_deduplicates_identical_queries(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """Two mosques with the same name+postcode should trigger only one API call."""
    mosque1 = _make_mosque(name="Duplicate Mosque", postcode="E1 1AA")
    mosque2 = _make_mosque(name="Duplicate Mosque", postcode="E1 1AA")
    db_session.add_all([mosque1, mosque2])
    await db_session.commit()

    fake_client = _FakeExaClient([ExaResult(title="Dup", url="https://dup.example/")])
    cache = SearchCache(cache_file=tmp_path / "cache.json", ttl_seconds=3600)
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client, cache=cache
    )
    # One API call for the deduplicated query
    assert len(fake_client.calls) == 1
    # But leads for both mosques
    assert len(leads) == 2
    assert {lead.mosque_id for lead in leads} == {mosque1.id, mosque2.id}


@pytest.mark.asyncio
async def test_provider_respects_limit(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """With limit=1, only one mosque is searched even when more are missing."""
    mosque1 = _make_mosque(name="First Mosque", postcode="E1 1AA")
    mosque2 = _make_mosque(name="Second Mosque", postcode="W1 1AA")
    db_session.add_all([mosque1, mosque2])
    await db_session.commit()

    fake_client = _FakeExaClient([ExaResult(title="X", url="https://x.example/")])
    cache = SearchCache(cache_file=tmp_path / "cache.json", ttl_seconds=3600)
    leads, result = await propose_search_engine_leads(
        db_session, exa_client=fake_client, cache=cache, limit=1
    )
    assert len(fake_client.calls) == 1
    assert len(leads) == 1


def test_build_query_quoted_name_plus_postcode() -> None:
    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    query = _build_query(mosque)
    assert query == '"East London Mosque" E1 1AA'


def test_build_query_returns_none_when_missing_fields() -> None:
    mosque = _make_mosque(name="", postcode="E1 1AA")
    assert _build_query(mosque) is None
    mosque = _make_mosque(name="Name", postcode="")
    assert _build_query(mosque) is None


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_engine_promotes_via_orchestrator(db_session: AsyncSession) -> None:
    from uk_jamaat_directory.services.website_discovery import run_website_discovery

    mosque = _make_mosque(name="East London Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    async def _stub_provider(session: AsyncSession):
        lead = WebsiteLead(
            mosque_id=mosque.id,
            url="https://www.eastlondonmosque.org.uk/",
            provider=WebsiteProvider.SEARCH_ENGINE,
            reason="exa_search_rank_1",
        )
        from uk_jamaat_directory.ingest.discovery.websites.types import (
            WebsiteLeadResult,
        )

        return [lead], WebsiteLeadResult(candidates_proposed=1)

    async def fake_fetch(url: str) -> tuple[str, str]:
        return (
            "East London Mosque & London Muslim Centre",
            "Welcome to the East London Mosque. Visit us at E1 1AA, London.",
        )

    # Patch verify_website to use our fake fetcher so the test stays offline.
    # We call run_website_discovery which calls verify_website internally.
    # The orchestrator does not accept a fetcher override, so we monkey-patch
    # the module-level _fetch_for_verification function.
    from uk_jamaat_directory.ingest.discovery.websites import verify as verify_module

    original_fetch = verify_module._fetch_for_verification

    async def _patched_fetch(url, *, user_agent, timeout):
        return await fake_fetch(url)

    verify_module._fetch_for_verification = _patched_fetch  # type: ignore[attr-defined]
    try:
        result = await run_website_discovery(
            db_session,
            providers=[_stub_provider],
            user_agent="test",
        )
    finally:
        verify_module._fetch_for_verification = original_fetch  # type: ignore[attr-defined]

    await db_session.commit()
    await db_session.refresh(mosque)
    assert mosque.website_url == "https://www.eastlondonmosque.org.uk/"
    assert result.promoted == 1


@pytest.mark.asyncio
async def test_search_engine_records_lead_when_unverifiable(
    db_session: AsyncSession,
) -> None:
    from uk_jamaat_directory.services.website_discovery import run_website_discovery

    mosque = _make_mosque(name="Test Mosque", postcode="E1 1AA")
    db_session.add(mosque)
    await db_session.commit()

    async def _stub_provider(session: AsyncSession):
        lead = WebsiteLead(
            mosque_id=mosque.id,
            url="https://www.test-mosque.org.uk/",
            provider=WebsiteProvider.SEARCH_ENGINE,
            reason="exa_search_rank_1",
        )
        from uk_jamaat_directory.ingest.discovery.websites.types import (
            WebsiteLeadResult,
        )

        return [lead], WebsiteLeadResult(candidates_proposed=1)

    from uk_jamaat_directory.ingest.discovery.websites import verify as verify_module

    original_fetch = verify_module._fetch_for_verification

    async def _patched_fetch(url, *, user_agent, timeout):
        return ("Totally Unrelated Page", "Nothing about mosques here.")

    verify_module._fetch_for_verification = _patched_fetch  # type: ignore[attr-defined]
    try:
        result = await run_website_discovery(
            db_session,
            providers=[_stub_provider],
            user_agent="test",
        )
    finally:
        verify_module._fetch_for_verification = original_fetch  # type: ignore[attr-defined]

    await db_session.commit()
    await db_session.refresh(mosque)
    assert mosque.website_url is None
    assert result.leads_recorded == 1
    assert result.no_match == 1
