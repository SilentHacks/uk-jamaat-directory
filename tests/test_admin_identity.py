from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    Prayer,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.models.core import (
    IdentityMatchReview,
    ModerationAction,
    Mosque,
    MosqueAlias,
    MosqueSource,
    ScheduleCandidate,
)

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


@pytest.mark.asyncio
async def test_admin_create_and_merge_mosque(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    create_response = await admin_client_with_db.post(
        "/v1/admin/mosques",
        headers=ADMIN_HEADERS,
        json={
            "name": "Admin Created Masjid",
            "city": "Leeds",
            "postcode": "LS1 1AA",
            "status": "active",
        },
    )
    assert create_response.status_code == 201
    canonical_id = create_response.json()["directory_mosque_id"]

    duplicate = Mosque(
        id=uuid.uuid4(),
        name="Duplicate Masjid",
        normalized_name="duplicate masjid",
        status=MosqueStatus.NEEDS_REVIEW,
    )
    db_session.add(duplicate)
    dup_source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=duplicate.id,
        source_type=SourceType.MANUAL,
        external_id="dup-1",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
    )
    db_session.add(dup_source)
    db_session.add(
        MosqueAlias(
            id=uuid.uuid4(),
            mosque_id=duplicate.id,
            alias="Old Name",
            normalized_alias="old name",
            source_type=SourceType.MANUAL,
        )
    )
    await db_session.flush()
    db_session.add(
        ScheduleCandidate(
            id=uuid.uuid4(),
            mosque_id=duplicate.id,
            source_id=dup_source.id,
            date=date(2026, 6, 4),
            prayer=Prayer.DHUHR,
            jamaat_time=time(13, 15),
        )
    )
    await db_session.commit()

    merge_response = await admin_client_with_db.post(
        f"/v1/admin/mosques/{canonical_id}/merge",
        headers=ADMIN_HEADERS,
        json={"duplicate_mosque_id": str(duplicate.id), "reason": "same site"},
    )
    assert merge_response.status_code == 200

    moved_source = await db_session.scalar(
        select(MosqueSource).where(MosqueSource.external_id == "dup-1")
    )
    assert moved_source is not None
    assert str(moved_source.mosque_id) == canonical_id

    moved_alias = await db_session.scalar(
        select(MosqueAlias).where(MosqueAlias.alias == "Old Name")
    )
    assert moved_alias is not None
    assert str(moved_alias.mosque_id) == canonical_id

    moved_candidate = await db_session.scalar(
        select(ScheduleCandidate).where(ScheduleCandidate.mosque_id == canonical_id)
    )
    assert moved_candidate is not None

    canonical_alias = await db_session.scalar(
        select(MosqueAlias).where(
            MosqueAlias.mosque_id == uuid.UUID(canonical_id),
            MosqueAlias.normalized_alias == "duplicate masjid",
        )
    )
    assert canonical_alias is not None

    actions = (await db_session.scalars(select(ModerationAction))).all()
    assert any(item.action == "merge_mosque" for item in actions)


@pytest.mark.asyncio
async def test_admin_discovery_lead_is_private_metadata(
    admin_client_with_db: AsyncClient,
) -> None:
    response = await admin_client_with_db.post(
        "/v1/admin/discovery-leads",
        headers=ADMIN_HEADERS,
        json={"query": "masjid near E2", "notes": "check manually"},
    )
    assert response.status_code == 200
    assert "Google-derived" in response.json()["message"]


@pytest.mark.asyncio
async def test_admin_identity_report(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    mosque1 = Mosque(
        id=uuid.uuid4(),
        name="Masjid A",
        normalized_name="masjid a",
        status=MosqueStatus.NEEDS_REVIEW,
        postcode="LS1 1AA",
        website_url="http://masjida.com",
    )
    mosque2 = Mosque(
        id=uuid.uuid4(),
        name="Masjid A",
        normalized_name="masjid a",
        status=MosqueStatus.NEEDS_REVIEW,
        postcode="LS1 1AA",
        website_url="",
    )
    db_session.add_all([mosque1, mosque2])

    source1 = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque1.id,
        source_type=SourceType.OPENSTREETMAP,
        external_id="osm-1",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.COMMUNITY,
    )
    source2 = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque1.id,
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-1",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
    )
    db_session.add_all([source1, source2])
    await db_session.flush()

    review = IdentityMatchReview(
        id=uuid.uuid4(),
        source_id=source2.id,
        proposed_mosque_id=mosque1.id,
        score=0.8500,
        decision="review",
        reasons={"reasons": ["name_match"]},
        status="pending",
    )
    db_session.add(review)
    await db_session.commit()

    response = await admin_client_with_db.get(
        "/v1/admin/identity-report",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mosque_count"] >= 2
    assert data["active_mosque_count"] == 0
    assert data["pending_identity_reviews"] == 1
    assert data["missing_website_count"] >= 1
    assert data["duplicate_candidate_count"] == 2
    assert len(data["duplicate_buckets"]) >= 1
    assert data["duplicate_buckets"][0]["normalized_name"] == "masjid a"


@pytest.mark.asyncio
async def test_admin_identity_reviews_flow(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    mosque = Mosque(
        id=uuid.uuid4(),
        name="Review Test Masjid",
        normalized_name="review test masjid",
        status=MosqueStatus.NEEDS_REVIEW,
        postcode="LS1 1AA",
    )
    db_session.add(mosque)

    source = MosqueSource(
        id=uuid.uuid4(),
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-rev-1",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
        display_name="Test Alias Name",
    )
    db_session.add(source)
    await db_session.flush()

    review = IdentityMatchReview(
        id=uuid.uuid4(),
        source_id=source.id,
        proposed_mosque_id=mosque.id,
        score=0.9200,
        decision="review",
        reasons={"reasons": ["name_similarity"]},
        status="pending",
        alternatives={
            "candidates": [
                {"mosque_id": str(mosque.id), "score": 0.92, "reasons": ["name_similarity"]}
            ]
        },
    )
    db_session.add(review)
    await db_session.commit()

    list_resp = await admin_client_with_db.get(
        "/v1/admin/identity-reviews",
        headers=ADMIN_HEADERS,
        params={"status": "pending"},
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["count"] >= 1
    items = [item for item in list_data["items"] if item["review_id"] == str(review.id)]
    assert len(items) == 1
    assert items[0]["score"] == 0.92
    assert "name_similarity" in items[0]["reasons"]
    assert len(items[0]["candidates"]) == 1
    assert items[0]["candidates"][0]["mosque_id"] == str(mosque.id)

    accept_resp = await admin_client_with_db.post(
        f"/v1/admin/identity-reviews/{review.id}/accept",
        headers=ADMIN_HEADERS,
        json={"mosque_id": str(mosque.id), "reason": "Looks good"},
    )
    assert accept_resp.status_code == 200
    accept_data = accept_resp.json()
    assert accept_data["changed"] == 1
    assert str(review.id) in accept_data["review_ids"]

    await db_session.refresh(review)
    await db_session.refresh(source)
    assert review.status == "accepted"
    assert source.mosque_id == mosque.id

    alias = await db_session.scalar(
        select(MosqueAlias).where(
            MosqueAlias.mosque_id == mosque.id,
            MosqueAlias.alias == "Test Alias Name",
        )
    )
    assert alias is not None

    source_rej = MosqueSource(
        id=uuid.uuid4(),
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-rev-2",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
    )
    db_session.add(source_rej)
    await db_session.flush()

    review_rej = IdentityMatchReview(
        id=uuid.uuid4(),
        source_id=source_rej.id,
        proposed_mosque_id=mosque.id,
        score=0.5100,
        decision="review",
        status="pending",
    )
    db_session.add(review_rej)
    await db_session.commit()

    reject_resp = await admin_client_with_db.post(
        f"/v1/admin/identity-reviews/{review_rej.id}/reject",
        headers=ADMIN_HEADERS,
        json={"reason": "Incorrect match"},
    )
    assert reject_resp.status_code == 200

    await db_session.refresh(review_rej)
    assert review_rej.status == "rejected"


@pytest.mark.asyncio
async def test_admin_bulk_accept_and_activate(
    admin_client_with_db: AsyncClient,
    db_session: AsyncSession,
) -> None:
    mosque1 = Mosque(
        id=uuid.uuid4(),
        name="Bulk Masjid One",
        normalized_name="bulk masjid one",
        status=MosqueStatus.NEEDS_REVIEW,
    )
    mosque2 = Mosque(
        id=uuid.uuid4(),
        name="Bulk Masjid Two",
        normalized_name="bulk masjid two",
        status=MosqueStatus.NEEDS_REVIEW,
    )
    db_session.add_all([mosque1, mosque2])

    source1 = MosqueSource(
        id=uuid.uuid4(),
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-bulk-1",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
    )
    source2 = MosqueSource(
        id=uuid.uuid4(),
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-bulk-2",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
    )
    db_session.add_all([source1, source2])
    await db_session.flush()

    review1 = IdentityMatchReview(
        id=uuid.uuid4(),
        source_id=source1.id,
        proposed_mosque_id=mosque1.id,
        score=0.9500,
        decision="review",
        status="pending",
    )
    review2 = IdentityMatchReview(
        id=uuid.uuid4(),
        source_id=source2.id,
        proposed_mosque_id=mosque2.id,
        score=0.9700,
        decision="review",
        status="pending",
        alternatives={
            "candidates": [
                {"mosque_id": str(mosque2.id), "score": 0.97},
                {"mosque_id": str(uuid.uuid4()), "score": 0.80},
            ]
        },
    )
    db_session.add_all([review1, review2])
    await db_session.commit()

    bulk_accept_resp = await admin_client_with_db.post(
        "/v1/admin/identity-reviews/bulk-accept",
        headers=ADMIN_HEADERS,
        json={"min_score": 0.90, "limit": 10, "dry_run": True},
    )
    assert bulk_accept_resp.status_code == 200
    bulk_accept_data = bulk_accept_resp.json()
    assert bulk_accept_data["dry_run"] is True
    assert bulk_accept_data["changed"] == 1
    assert str(review1.id) in bulk_accept_data["review_ids"]

    await db_session.refresh(review1)
    assert review1.status == "pending"

    bulk_accept_resp = await admin_client_with_db.post(
        "/v1/admin/identity-reviews/bulk-accept",
        headers=ADMIN_HEADERS,
        json={"min_score": 0.90, "limit": 10, "dry_run": False},
    )
    assert bulk_accept_resp.status_code == 200
    bulk_accept_data = bulk_accept_resp.json()
    assert bulk_accept_data["dry_run"] is False
    assert bulk_accept_data["changed"] == 1

    await db_session.refresh(review1)
    assert review1.status == "accepted"

    mosque3 = Mosque(
        id=uuid.uuid4(),
        name="Public Source Mosque",
        normalized_name="public source mosque",
        status=MosqueStatus.NEEDS_REVIEW,
    )
    db_session.add(mosque3)

    source3 = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque3.id,
        source_type=SourceType.OPENSTREETMAP,
        external_id="osm-bulk-3",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.COMMUNITY,
    )
    db_session.add(source3)
    await db_session.commit()

    bulk_activate_resp = await admin_client_with_db.post(
        "/v1/admin/identity/mosques/bulk-activate",
        headers=ADMIN_HEADERS,
        json={"require_public_source": True, "dry_run": False},
    )
    assert bulk_activate_resp.status_code == 200
    bulk_activate_data = bulk_activate_resp.json()
    assert bulk_activate_data["changed"] == 1
    assert str(mosque3.id) in bulk_activate_data["mosque_ids"]

    await db_session.refresh(mosque3)
    assert mosque3.status == MosqueStatus.ACTIVE
