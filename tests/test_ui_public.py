from __future__ import annotations

import uuid

import pytest
from fixtures import seed_crawled_mosque, seed_public_mosque_bundle
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_index_lists_active_mosques(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_public_mosque_bundle(db_session)
    resp = await client_with_db.get("/")
    assert resp.status_code == 200
    assert "Test Masjid" in resp.text
    assert "/assets/htmx.min.js" in resp.text  # self-hosted htmx, CSP-safe


@pytest.mark.asyncio
async def test_search_partial_filters_by_query(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_public_mosque_bundle(db_session)
    hit = await client_with_db.get("/partials/mosques", params={"q": "Test"})
    assert hit.status_code == 200
    assert "Test Masjid" in hit.text

    miss = await client_with_db.get("/partials/mosques", params={"q": "Nonexistent"})
    assert miss.status_code == 200
    assert "Test Masjid" not in miss.text
    assert "No mosques found" in miss.text


@pytest.mark.asyncio
async def test_mosque_detail_shows_weekly_timetable(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    mosque = bundle["mosque"]
    # The seeded public occurrence is Fajr on 2026-06-05 (week of Mon 2026-06-01).
    resp = await client_with_db.get(f"/mosques/{mosque.id}", params={"week": "2026-06-01"})
    assert resp.status_code == 200
    assert "Test Masjid" in resp.text
    assert "Weekly timetable" in resp.text
    assert "03:45" in resp.text  # published Fajr jamaat time
    # Private-source Dhuhr must not leak into the public grid.
    assert "13:15" not in resp.text


@pytest.mark.asyncio
async def test_mosque_detail_unknown_returns_404(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client_with_db.get(f"/mosques/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_index_offers_crawled_filter(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    await seed_public_mosque_bundle(db_session)
    resp = await client_with_db.get("/")
    assert resp.status_code == 200
    assert 'name="crawled"' in resp.text


@pytest.mark.asyncio
async def test_crawled_filter_includes_only_crawled_mosques(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    # seed_public_mosque_bundle's "Test Masjid" times come from MyLocalMasjid,
    # not the website-crawl pipeline, so it must be excluded when crawled=true.
    bundle = await seed_public_mosque_bundle(db_session)
    await seed_crawled_mosque(db_session, dataset_version=bundle["dataset_version"])

    unfiltered = await client_with_db.get("/partials/mosques")
    assert "Test Masjid" in unfiltered.text
    assert "Crawled Masjid" in unfiltered.text

    filtered = await client_with_db.get("/partials/mosques", params={"crawled": "true"})
    assert filtered.status_code == 200
    assert "Crawled Masjid" in filtered.text
    assert "Test Masjid" not in filtered.text


@pytest.mark.asyncio
async def test_crawled_filter_combines_with_search_query(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    await seed_crawled_mosque(db_session, dataset_version=bundle["dataset_version"])

    # Query matches the crawled mosque -> shown.
    hit = await client_with_db.get(
        "/partials/mosques", params={"q": "Crawled", "crawled": "true"}
    )
    assert "Crawled Masjid" in hit.text

    # Query matches a non-crawled mosque -> excluded by the crawled filter.
    miss = await client_with_db.get(
        "/partials/mosques", params={"q": "Test", "crawled": "true"}
    )
    assert "Test Masjid" not in miss.text
    assert "No mosques found" in miss.text


@pytest.mark.asyncio
async def test_about_page_renders_without_db(client_with_db: AsyncClient) -> None:
    resp = await client_with_db.get("/about")
    assert resp.status_code == 200
    assert "API reference" in resp.text


@pytest.mark.asyncio
async def test_public_pages_support_head(
    client_with_db: AsyncClient, db_session: AsyncSession
) -> None:
    # Public pages are served by the SSR app (not a static file server), so the
    # GET routes must also answer HEAD. Monitoring/CDN health checks (and the
    # deploy smoke test's `curl -I /`) rely on this; a bare @router.get would
    # 405 on HEAD.
    bundle = await seed_public_mosque_bundle(db_session)
    for path in ("/", "/about", f"/mosques/{bundle['mosque'].id}"):
        resp = await client_with_db.head(path)
        assert resp.status_code == 200, f"HEAD {path} returned {resp.status_code}"

