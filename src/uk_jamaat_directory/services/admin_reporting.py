from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.domain import (
    CandidateStatus,
    ClaimStatus,
    CorrectionStatus,
    MosqueStatus,
)
from uk_jamaat_directory.models.core import (
    Correction,
    IdentityMatchReview,
    Mosque,
    MosqueClaim,
    MosqueSource,
    ScheduleCandidate,
    SourceHealth,
)


@dataclass
class AdminCoverageReport:
    generated_at: datetime
    mosque_count: int
    active_mosque_count: int
    source_count: int
    pending_candidates: int
    approved_candidates: int
    rejected_candidates: int
    open_corrections: int
    open_claims: int
    policy_counts: dict[str, int]
    source_type_counts: dict[str, int]
    stale_source_count: int
    pending_identity_reviews: int
    missing_postcode_count: int
    missing_coordinates_count: int
    missing_website_count: int
    duplicate_candidate_count: int


@dataclass
class SourceOverlap:
    source_set: str
    mosque_count: int


@dataclass
class DuplicateBucket:
    normalized_name: str
    postcode: str | None
    mosque_count: int
    mosque_ids: list[uuid.UUID]


@dataclass
class IdentityQualityReport:
    generated_at: datetime
    mosque_count: int
    active_mosque_count: int
    status_counts: dict[str, int]
    source_count: int
    source_type_counts: dict[str, int]
    policy_counts: dict[str, int]
    source_overlaps: list[SourceOverlap]
    linked_source_count: int
    unlinked_source_count: int
    pending_identity_reviews: int
    missing_postcode_count: int
    missing_coordinates_count: int
    missing_website_count: int
    active_missing_website_count: int
    duplicate_candidate_count: int
    duplicate_buckets: list[DuplicateBucket]


async def build_admin_coverage(session: AsyncSession) -> AdminCoverageReport:
    settings = get_settings()
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=settings.source_last_seen_stale_days)

    mosque_count = int(
        (await session.execute(select(func.count()).select_from(Mosque))).scalar_one()
    )
    active_mosque_count = int(
        (
            await session.execute(
                select(func.count()).select_from(Mosque).where(Mosque.status == MosqueStatus.ACTIVE)
            )
        ).scalar_one()
    )
    source_count = int(
        (await session.execute(select(func.count()).select_from(MosqueSource))).scalar_one()
    )

    policy_counts: dict[str, int] = {}
    for policy, count in (
        await session.execute(
            select(MosqueSource.publication_policy, func.count()).group_by(
                MosqueSource.publication_policy
            )
        )
    ).all():
        policy_counts[policy.value] = count

    source_type_counts: dict[str, int] = {}
    for source_type, count in (
        await session.execute(
            select(MosqueSource.source_type, func.count()).group_by(MosqueSource.source_type)
        )
    ).all():
        source_type_counts[source_type.value] = count

    stale_source_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MosqueSource)
                .where(
                    (MosqueSource.last_seen_at.is_(None))
                    | (MosqueSource.last_seen_at < stale_cutoff)
                )
            )
        ).scalar_one()
    )
    pending_identity_reviews = int(
        (
            await session.execute(
                select(func.count())
                .select_from(IdentityMatchReview)
                .where(IdentityMatchReview.status == "pending")
            )
        ).scalar_one()
    )
    missing_postcode_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Mosque)
                .where((Mosque.postcode.is_(None)) | (Mosque.postcode == ""))
            )
        ).scalar_one()
    )
    missing_coordinates_count = int(
        (
            await session.execute(
                select(func.count()).select_from(Mosque).where(Mosque.location.is_(None))
            )
        ).scalar_one()
    )
    missing_website_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Mosque)
                .where((Mosque.website_url.is_(None)) | (Mosque.website_url == ""))
            )
        ).scalar_one()
    )
    duplicate_candidate_count = await _count_duplicate_candidate_mosques(session)

    pending_candidates = 0
    approved_candidates = 0
    rejected_candidates = 0
    candidate_counts = await session.execute(
        select(ScheduleCandidate.status, func.count()).group_by(ScheduleCandidate.status)
    )
    for status, count in candidate_counts.all():
        if status == CandidateStatus.PENDING:
            pending_candidates = count
        elif status == CandidateStatus.APPROVED:
            approved_candidates = count
        elif status == CandidateStatus.REJECTED:
            rejected_candidates = count

    open_corrections = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Correction)
                .where(Correction.status == CorrectionStatus.PENDING)
            )
        ).scalar_one()
    )
    open_claims = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MosqueClaim)
                .where(MosqueClaim.status == ClaimStatus.PENDING)
            )
        ).scalar_one()
    )

    return AdminCoverageReport(
        generated_at=now,
        mosque_count=mosque_count,
        active_mosque_count=active_mosque_count,
        source_count=source_count,
        pending_candidates=pending_candidates,
        approved_candidates=approved_candidates,
        rejected_candidates=rejected_candidates,
        open_corrections=open_corrections,
        open_claims=open_claims,
        policy_counts=policy_counts,
        source_type_counts=source_type_counts,
        stale_source_count=stale_source_count,
        pending_identity_reviews=pending_identity_reviews,
        missing_postcode_count=missing_postcode_count,
        missing_coordinates_count=missing_coordinates_count,
        missing_website_count=missing_website_count,
        duplicate_candidate_count=duplicate_candidate_count,
    )


async def build_identity_quality_report(session: AsyncSession) -> IdentityQualityReport:
    coverage = await build_admin_coverage(session)
    now = coverage.generated_at

    status_counts: dict[str, int] = {}
    for status, count in (
        await session.execute(select(Mosque.status, func.count()).group_by(Mosque.status))
    ).all():
        status_counts[status.value] = count

    linked_source_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MosqueSource)
                .where(MosqueSource.mosque_id.is_not(None))
            )
        ).scalar_one()
    )
    unlinked_source_count = coverage.source_count - linked_source_count
    active_missing_website_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Mosque)
                .where(Mosque.status == MosqueStatus.ACTIVE)
                .where((Mosque.website_url.is_(None)) | (Mosque.website_url == ""))
            )
        ).scalar_one()
    )

    return IdentityQualityReport(
        generated_at=now,
        mosque_count=coverage.mosque_count,
        active_mosque_count=coverage.active_mosque_count,
        status_counts=status_counts,
        source_count=coverage.source_count,
        source_type_counts=coverage.source_type_counts,
        policy_counts=coverage.policy_counts,
        source_overlaps=await _build_source_overlaps(session),
        linked_source_count=linked_source_count,
        unlinked_source_count=unlinked_source_count,
        pending_identity_reviews=coverage.pending_identity_reviews,
        missing_postcode_count=coverage.missing_postcode_count,
        missing_coordinates_count=coverage.missing_coordinates_count,
        missing_website_count=coverage.missing_website_count,
        active_missing_website_count=active_missing_website_count,
        duplicate_candidate_count=coverage.duplicate_candidate_count,
        duplicate_buckets=await _build_duplicate_buckets(session),
    )


async def _count_duplicate_candidate_mosques(session: AsyncSession) -> int:
    rows = (
        await session.execute(
            select(Mosque.normalized_name, Mosque.postcode, func.count())
            .where(Mosque.status != MosqueStatus.DUPLICATE)
            .where(Mosque.normalized_name.is_not(None))
            .group_by(Mosque.normalized_name, Mosque.postcode)
            .having(func.count() > 1)
        )
    ).all()
    return sum(int(row[2]) for row in rows)


async def _build_duplicate_buckets(
    session: AsyncSession, *, limit: int = 25
) -> list[DuplicateBucket]:
    rows = (
        await session.execute(
            select(
                Mosque.normalized_name,
                Mosque.postcode,
                func.count().label("mosque_count"),
                func.array_agg(Mosque.id).label("mosque_ids"),
            )
            .where(Mosque.status != MosqueStatus.DUPLICATE)
            .where(Mosque.normalized_name.is_not(None))
            .group_by(Mosque.normalized_name, Mosque.postcode)
            .having(func.count() > 1)
            .order_by(func.count().desc(), Mosque.normalized_name.asc())
            .limit(limit)
        )
    ).all()
    return [
        DuplicateBucket(
            normalized_name=row[0],
            postcode=row[1],
            mosque_count=int(row[2]),
            mosque_ids=list(row[3] or []),
        )
        for row in rows
    ]


async def _build_source_overlaps(session: AsyncSession) -> list[SourceOverlap]:
    rows = (
        await session.execute(
            select(MosqueSource.mosque_id, MosqueSource.source_type).where(
                MosqueSource.mosque_id.is_not(None)
            )
        )
    ).all()
    source_sets_by_mosque: dict[uuid.UUID, set[str]] = {}
    for mosque_id, source_type in rows:
        source_sets_by_mosque.setdefault(mosque_id, set()).add(source_type.value)

    counts: dict[str, int] = {}
    for source_types in source_sets_by_mosque.values():
        key = "+".join(sorted(source_types))
        counts[key] = counts.get(key, 0) + 1
    return [
        SourceOverlap(source_set=source_set, mosque_count=count)
        for source_set, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


async def list_source_health(
    session: AsyncSession,
    *,
    mosque_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[tuple[SourceHealth, MosqueSource]], int]:
    stmt = (
        select(SourceHealth, MosqueSource)
        .join(MosqueSource, SourceHealth.source_id == MosqueSource.id)
        .order_by(SourceHealth.updated_at.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(SourceHealth)
        .join(MosqueSource, SourceHealth.source_id == MosqueSource.id)
    )
    if mosque_id is not None:
        stmt = stmt.where(MosqueSource.mosque_id == mosque_id)
        count_stmt = count_stmt.where(MosqueSource.mosque_id == mosque_id)

    total = int((await session.execute(count_stmt)).scalar_one())
    rows = list((await session.execute(stmt.offset(offset).limit(limit))).all())
    return rows, total
