from __future__ import annotations

import uuid

import pytest
from fixtures import seed_public_mosque_bundle
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
async def test_about_page_renders_without_db(client_with_db: AsyncClient) -> None:
    resp = await client_with_db.get("/about")
    assert resp.status_code == 200
    assert "API reference" in resp.text
