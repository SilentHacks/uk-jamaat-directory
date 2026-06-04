from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    CandidateStatus,
    ClaimStatus,
    CorrectionStatus,
    MosqueStatus,
)
from uk_jamaat_directory.models.core import (
    Correction,
    Mosque,
    MosqueClaim,
    MosqueSource,
    ScheduleCandidate,
    SourceHealth,
)

STALE_AFTER_DAYS = 30


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


async def build_admin_coverage(session: AsyncSession) -> AdminCoverageReport:
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=STALE_AFTER_DAYS)

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
    source_type_counts: dict[str, int] = {}
    stale_source_count = 0
    sources = (await session.scalars(select(MosqueSource))).all()
    for source in sources:
        policy = source.publication_policy.value
        policy_counts[policy] = policy_counts.get(policy, 0) + 1
        source_type = source.source_type.value
        source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1
        if source.last_seen_at is None or source.last_seen_at < stale_cutoff:
            stale_source_count += 1

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
    )


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
