from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uk_jamaat_directory.domain import MosqueStatus
from uk_jamaat_directory.exports.types import ExportDataset, SourceCountSummary
from uk_jamaat_directory.models.core import (
    ChangeEvent,
    DatasetVersion,
    Mosque,
    MosqueSource,
    ScheduleOccurrence,
)
from uk_jamaat_directory.services.mappers import (
    change_event_public,
    mosque_detail,
    schedule_occurrence,
)
from uk_jamaat_directory.services.public_policy import (
    is_public_source_policy,
    public_source_filter,
)

DEFAULT_ATTRIBUTION = "UK Jamaat Directory"


async def collect_export_dataset(
    session: AsyncSession,
    version: DatasetVersion,
) -> ExportDataset:
    mosque_rows = (
        (
            await session.execute(
                select(Mosque)
                .where(Mosque.status == MosqueStatus.ACTIVE)
                .options(
                    selectinload(Mosque.aliases),
                    selectinload(Mosque.sources),
                    selectinload(Mosque.attributes),
                )
                .order_by(Mosque.normalized_name.asc(), Mosque.id.asc())
            )
        )
        .scalars()
        .all()
    )

    mosques = [
        mosque_detail(
            mosque,
            aliases=list(mosque.aliases),
            sources=list(mosque.sources),
            attributes=mosque.attributes,
        )
        for mosque in mosque_rows
    ]

    occurrence_rows = (
        await session.execute(
            select(ScheduleOccurrence, MosqueSource)
            .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
            .join(Mosque, ScheduleOccurrence.mosque_id == Mosque.id)
            .where(ScheduleOccurrence.dataset_version_id == version.id)
            .where(Mosque.status == MosqueStatus.ACTIVE)
            .where(public_source_filter())
            .order_by(
                ScheduleOccurrence.mosque_id.asc(),
                ScheduleOccurrence.date.asc(),
                ScheduleOccurrence.prayer.asc(),
                ScheduleOccurrence.session_number.asc(),
            )
        )
    ).all()

    occurrences = [
        schedule_occurrence(
            occurrence,
            source=source,
            dataset_version=version.version,
        )
        for occurrence, source in occurrence_rows
    ]

    change_rows = (
        await session.execute(
            select(ChangeEvent, DatasetVersion.version)
            .outerjoin(DatasetVersion, ChangeEvent.dataset_version_id == DatasetVersion.id)
            .where(ChangeEvent.dataset_version_id == version.id)
            .order_by(ChangeEvent.id.asc())
        )
    ).all()
    changes = [
        change_event_public(event, dataset_version=change_version)
        for event, change_version in change_rows
    ]

    source_counts = await _count_sources(session)
    attribution = _build_attribution(mosque_rows)

    return ExportDataset(
        version=version.version,
        schema_version=version.schema_version,
        published_at=version.published_at,
        mosques=mosques,
        occurrences=occurrences,
        changes=changes,
        attribution=attribution,
        source_counts=source_counts,
    )


async def _count_sources(session: AsyncSession) -> SourceCountSummary:
    rows = (
        await session.execute(
            select(MosqueSource.publication_policy, func.count())
            .join(Mosque, MosqueSource.mosque_id == Mosque.id)
            .where(Mosque.status == MosqueStatus.ACTIVE)
            .where(MosqueSource.mosque_id.is_not(None))
            .group_by(MosqueSource.publication_policy)
        )
    ).all()

    public_count = 0
    excluded_count = 0
    for policy, count in rows:
        if is_public_source_policy(policy):
            public_count += int(count)
        else:
            excluded_count += int(count)

    return SourceCountSummary(
        public_sources=public_count,
        excluded_restricted_sources=excluded_count,
        total_linked_sources=public_count + excluded_count,
    )


def _build_attribution(mosques: list[Mosque]) -> list[str]:
    lines: list[str] = [DEFAULT_ATTRIBUTION]
    seen: set[str] = {DEFAULT_ATTRIBUTION}

    for mosque in mosques:
        for source in mosque.sources:
            if not is_public_source_policy(source.publication_policy):
                continue
            if source.attribution:
                stripped = source.attribution.strip()
                if stripped and stripped not in seen:
                    seen.add(stripped)
                    lines.append(stripped)
    return lines

