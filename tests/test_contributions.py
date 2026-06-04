from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.models.core import MosqueSource
from uk_jamaat_directory.schemas.public import MosqueDetailPublic


@pytest.mark.asyncio
async def test_community_submission_stores_private_contact(
    client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    response = await client_with_db.post(
        "/v1/contributions/mosques",
        json={
            "name": "Community Submitted Masjid",
            "city": "Birmingham",
            "postcode": "B1 1AA",
            "submitter_name": "Private Person",
            "submitter_email": "private@example.org",
            "message": "Missing from map",
        },
    )
    assert response.status_code == 202
    submission_id = response.json()["submission_id"]

    source = await db_session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == SourceType.COMMUNITY,
            MosqueSource.external_id == submission_id,
        )
    )
    assert source is not None
    assert source.metadata_["submitter_email"] == "private@example.org"
    assert source.publication_policy.value == "unknown"

    public_fields = set(MosqueDetailPublic.model_fields)
    assert "submitter_email" not in public_fields
