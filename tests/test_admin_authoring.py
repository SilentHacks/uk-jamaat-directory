from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    AuthoringTaskStatus,
    Confidence,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    MosqueSource,
)

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


async def _seed_source_with_task(
    session: AsyncSession,
    *,
    status_value: str = AuthoringTaskStatus.AWAITING_REVIEW.value,
    target_kind: str = "html",
) -> tuple[Mosque, MosqueSource, ExtractorAuthoringTask]:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Authoring Test Masjid",
        normalized_name="authoring test masjid",
        website_url="https://authoring.test/",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url="https://authoring.test/",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    task = ExtractorAuthoringTask(
        id=uuid.uuid4(),
        source_id=source.id,
        status=status_value,
        target_kind=target_kind,
        discovered_url="https://authoring.test/prayer-times",
        extractor_key="authoring_test_draft",
        extractor_version="2026.06.08.1",
        script_path="src/.../authoring_test_draft.py",
        agent_model="opencode-go/deepseek-v4-flash",
        agent_duration_ms=1500,
        validation_issues=[],
        error=None,
    )
    session.add(mosque)
    session.add(source)
    session.add(task)
    await session.flush()
    return mosque, source, task


@pytest.mark.asyncio
async def test_admin_list_authoring_tasks_returns_seeded_rows(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _mosque, _source, task = await _seed_source_with_task(db_session)
    response = await admin_client_with_db.get(
        "/v1/admin/authoring",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    item = next(entry for entry in payload["items"] if entry["id"] == str(task.id))
    assert item["status"] == AuthoringTaskStatus.AWAITING_REVIEW.value
    assert item["extractor_key"] == "authoring_test_draft"
    assert item["target_kind"] == "html"


@pytest.mark.asyncio
async def test_admin_list_authoring_tasks_filters_by_status(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    _mosque, _source, task = await _seed_source_with_task(
        db_session,
        status_value=AuthoringTaskStatus.SKIPPED_REVIEW.value,
        target_kind="pdf",
    )
    response = await admin_client_with_db.get(
        "/v1/admin/authoring",
        headers=ADMIN_HEADERS,
        params={"status": AuthoringTaskStatus.SKIPPED_REVIEW.value},
    )
    assert response.status_code == 200
    payload = response.json()
    assert any(item["id"] == str(task.id) for item in payload["items"])
    assert all(
        item["status"] == AuthoringTaskStatus.SKIPPED_REVIEW.value for item in payload["items"]
    )
