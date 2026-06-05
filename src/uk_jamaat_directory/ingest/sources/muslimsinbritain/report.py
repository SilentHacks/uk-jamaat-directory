from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.models.core import IdentityMatchReview, Mosque, MosqueSource


@dataclass
class MibCoverageReport:
    source_count: int = 0
    linked_mosque_count: int = 0
    pending_reviews: int = 0
    missing_coordinates: list[str] = field(default_factory=list)
    missing_postcode: list[str] = field(default_factory=list)
    stale_sources: list[str] = field(default_factory=list)
    country_counts: dict[str, int] = field(default_factory=dict)
    policy_counts: dict[str, int] = field(default_factory=dict)
    record_class_counts: dict[str, int] = field(default_factory=dict)
    attribution_summary: str = (
        "MuslimsInBritain.org records default to publication_policy=unknown until ADR 0011 "
        "records the redistribution decision."
    )
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "source_count": self.source_count,
            "linked_mosque_count": self.linked_mosque_count,
            "pending_reviews": self.pending_reviews,
            "country_counts": self.country_counts,
            "policy_counts": self.policy_counts,
            "record_class_counts": self.record_class_counts,
            "missing_coordinates": self.missing_coordinates,
            "missing_postcode": self.missing_postcode,
            "stale_sources": self.stale_sources,
            "attribution_summary": self.attribution_summary,
        }


async def build_coverage_report(session: AsyncSession) -> MibCoverageReport:
    settings = get_settings()
    report = MibCoverageReport()
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(days=settings.mib_report_stale_days)

    sources = (
        await session.scalars(
            select(MosqueSource).where(MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN)
        )
    ).all()
    report.source_count = len(sources)
    report.linked_mosque_count = sum(1 for source in sources if source.mosque_id is not None)

    mosques_by_id: dict[object, Mosque] = {}
    mosque_ids = [source.mosque_id for source in sources if source.mosque_id is not None]
    if mosque_ids:
        mosques = (await session.scalars(select(Mosque).where(Mosque.id.in_(mosque_ids)))).all()
        mosques_by_id = {mosque.id: mosque for mosque in mosques}

    for source in sources:
        report.policy_counts[source.publication_policy.value] = (
            report.policy_counts.get(source.publication_policy.value, 0) + 1
        )
        record_class = str(source.metadata_.get("record_class") or "unknown")
        report.record_class_counts[record_class] = (
            report.record_class_counts.get(record_class, 0) + 1
        )
        country = _source_country(source, mosques_by_id)
        report.country_counts[country] = report.country_counts.get(country, 0) + 1

        if source.last_seen_at is None or source.last_seen_at < stale_cutoff:
            report.stale_sources.append(source.external_id)

        mosque = mosques_by_id.get(source.mosque_id)
        if mosque is None:
            continue
        if mosque.location is None:
            report.missing_coordinates.append(source.external_id)
        if not mosque.postcode:
            report.missing_postcode.append(source.external_id)

    report.pending_reviews = await session.scalar(
        select(func.count())
        .select_from(IdentityMatchReview)
        .join(MosqueSource, IdentityMatchReview.source_id == MosqueSource.id)
        .where(
            MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN,
            IdentityMatchReview.status == "pending",
        )
    ) or 0
    return report


def _source_country(source: MosqueSource, mosques_by_id: dict[object, Mosque]) -> str:
    mosque = mosques_by_id.get(source.mosque_id)
    if mosque is not None and mosque.country:
        return mosque.country
    value = source.metadata_.get("country")
    if isinstance(value, str) and value:
        return value
    return "unknown"
