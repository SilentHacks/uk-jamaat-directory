from __future__ import annotations

import pytest
from fixtures import seed_public_mosque_bundle
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_list_and_get_mosque(client_with_db: AsyncClient, db_session: AsyncSession) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    mosque = bundle["mosque"]

    list_response = await client_with_db.get("/v1/mosques")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["count"] == 1
    assert list_payload["items"][0]["directory_mosque_id"] == str(mosque.id)

    detail_response = await client_with_db.get(f"/v1/mosques/{mosque.id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["name"] == "Test Masjid"
    assert len(detail_payload["sources"]) == 1
    assert detail_payload["sources"][0]["source_type"] == "mylocalmasjid"


@pytest.mark.asyncio
async def test_mosque_times_exclude_private_sources(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    mosque = bundle["mosque"]

    response = await client_with_db.get(
        f"/v1/mosques/{mosque.id}/times",
        params={"from": "2026-06-05", "to": "2026-06-05"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["prayer"] == "fajr"
    assert payload["items"][0]["dataset_version"] == "2026-06-04.1"


@pytest.mark.asyncio
async def test_nearby_times_returns_public_occurrences(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    await seed_public_mosque_bundle(db_session)

    response = await client_with_db.get(
        "/v1/times/nearby",
        params={
            "lat": 51.5154,
            "lng": -0.0759,
            "radius_m": 5000,
            "date": "2026-06-05",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["occurrence"]["prayer"] == "fajr"


@pytest.mark.asyncio
async def test_changes_and_snapshots(client_with_db: AsyncClient, db_session: AsyncSession) -> None:
    bundle = await seed_public_mosque_bundle(db_session)

    changes_response = await client_with_db.get("/v1/changes")
    assert changes_response.status_code == 200
    changes_payload = changes_response.json()
    assert changes_payload["count"] == 1
    assert changes_payload["items"][0]["event_type"] == "occurrence_published"

    snapshot_response = await client_with_db.get(
        "/v1/snapshots/latest", params={"format": "ndjson"}
    )
    assert snapshot_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    assert snapshot_payload["version"] == bundle["dataset_version"].version
    assert snapshot_payload["formats"][0]["format"] == "ndjson"


@pytest.mark.asyncio
async def test_search_requires_filter(client_with_db: AsyncClient) -> None:
    response = await client_with_db.get("/v1/mosques/search")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
