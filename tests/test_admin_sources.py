from __future__ import annotations

import pytest
from fixtures import seed_public_mosque_bundle
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy
from uk_jamaat_directory.models.core import ModerationAction, MosqueSource

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.asyncio
async def test_admin_list_and_patch_source(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    bundle = await seed_public_mosque_bundle(db_session)
    source: MosqueSource = bundle["public_source"]

    list_response = await admin_client_with_db.get(
        "/v1/admin/sources",
        headers=ADMIN_HEADERS,
        params={"mosque_id": str(bundle["mosque"].id)},
    )
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] >= 1
    assert any(item["source_id"] == str(source.id) for item in payload["items"])

    patch_response = await admin_client_with_db.patch(
        f"/v1/admin/sources/{source.id}",
        headers=ADMIN_HEADERS,
        json={"publication_policy": "private_use_only", "confidence": "verified"},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["publication_policy"] == "private_use_only"

    await db_session.refresh(source)
    assert source.publication_policy == SourcePublicationPolicy.PRIVATE_USE_ONLY

    audit = await db_session.scalar(
        select(ModerationAction).where(
            ModerationAction.entity_id == source.id,
            ModerationAction.action == "update_source",
        )
    )
    assert audit is not None
