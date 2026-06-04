from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.domain import CandidateStatus, CorrectionStatus, SourceType
from uk_jamaat_directory.models.core import (
    Correction,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
)


@dataclass
class MyLocalMasjidCoverageReport:
    source_count: int = 0
    linked_mosque_count: int = 0
    pending_candidates: int = 0
    approved_candidates: int = 0
    rejected_candidates: int = 0
    stale_sources: list[str] = field(default_factory=list)
    policy_counts: dict[str, int] = field(default_factory=dict)
    sources_missing_recent_schedules: list[str] = field(default_factory=list)
    open_corrections: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "source_count": self.source_count,
            "linked_mosque_count": self.linked_mosque_count,
            "pending_candidates": self.pending_candidates,
            "approved_candidates": self.approved_candidates,
            "rejected_candidates": self.rejected_candidates,
            "policy_counts": self.policy_counts,
            "stale_sources": self.stale_sources,
            "sources_missing_recent_schedules": self.sources_missing_recent_schedules,
            "open_corrections": self.open_corrections,
        }


async def build_coverage_report(session: AsyncSession) -> MyLocalMasjidCoverageReport:
    settings = get_settings()
    report = MyLocalMasjidCoverageReport()
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=settings.mlm_report_stale_days)
    schedule_cutoff = date.today()

    sources = (
        await session.scalars(
            select(MosqueSource).where(MosqueSource.source_type == SourceType.MYLOCALMASJID)
        )
    ).all()
    report.source_count = len(sources)
    report.linked_mosque_count = sum(1 for source in sources if source.mosque_id is not None)

    for source in sources:
        policy = source.publication_policy.value
        report.policy_counts[policy] = report.policy_counts.get(policy, 0) + 1
        if source.last_seen_at is None or source.last_seen_at < stale_cutoff:
            report.stale_sources.append(source.external_id)

    candidate_counts = await session.execute(
        select(ScheduleCandidate.status, func.count())
        .join(MosqueSource, ScheduleCandidate.source_id == MosqueSource.id)
        .where(MosqueSource.source_type == SourceType.MYLOCALMASJID)
        .group_by(ScheduleCandidate.status)
    )
    for status, count in candidate_counts.all():
        if status == CandidateStatus.PENDING:
            report.pending_candidates = count
        elif status == CandidateStatus.APPROVED:
            report.approved_candidates = count
        elif status == CandidateStatus.REJECTED:
            report.rejected_candidates = count

    for source in sources:
        if source.mosque_id is None:
            report.sources_missing_recent_schedules.append(source.external_id)
            continue
        recent = await session.scalar(
            select(func.count())
            .select_from(ScheduleCandidate)
            .where(
                ScheduleCandidate.source_id == source.id,
                ScheduleCandidate.date >= schedule_cutoff,
            )
        )
        if not recent:
            report.sources_missing_recent_schedules.append(source.external_id)

    report.open_corrections = (
        await session.scalar(
            select(func.count())
            .select_from(Correction)
            .join(Mosque, Correction.mosque_id == Mosque.id)
            .join(MosqueSource, MosqueSource.mosque_id == Mosque.id)
            .where(
                MosqueSource.source_type == SourceType.MYLOCALMASJID,
                Correction.status == CorrectionStatus.PENDING,
            )
        )
        or 0
    )

    return report
