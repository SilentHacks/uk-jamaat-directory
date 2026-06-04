from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import CandidateStatus, ChangeEventType, FreshnessStatus
from uk_jamaat_directory.models.core import (
    ChangeEvent,
    DatasetVersion,
    Mosque,
    MosqueSource,
    ScheduleCandidate,
    ScheduleOccurrence,
)
from uk_jamaat_directory.schedules.dataset import (
    create_published_dataset_version,
    get_latest_published_version,
)
from uk_jamaat_directory.schedules.freshness import (
    recompute_source_health,
    refresh_occurrence_freshness_for_source,
)
from uk_jamaat_directory.schedules.gates import can_publish_candidate
from uk_jamaat_directory.schedules.keys import (
    OccurrenceKey,
    occurrence_key,
    occurrence_key_from_row,
    prayer_key,
)
from uk_jamaat_directory.schedules.prefetch import build_validation_batch_context
from uk_jamaat_directory.schedules.types import PublishResult, ValidateBatchResult
from uk_jamaat_directory.schedules.validation import (
    status_after_validation,
    validate_candidate,
)
from uk_jamaat_directory.services.public_policy import public_source_filter


@dataclass(frozen=True)
class PublishableCandidate:
    candidate: ScheduleCandidate
    source: MosqueSource
    mosque: Mosque


def _candidate_filters(
    stmt,
    *,
    source_id: uuid.UUID | None,
    mosque_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
):
    if source_id is not None:
        stmt = stmt.where(ScheduleCandidate.source_id == source_id)
    if mosque_id is not None:
        stmt = stmt.where(ScheduleCandidate.mosque_id == mosque_id)
    if date_from is not None:
        stmt = stmt.where(ScheduleCandidate.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(ScheduleCandidate.date <= date_to)
    return stmt


def _publish_filters_active(
    *,
    source_id: uuid.UUID | None,
    mosque_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    return any(value is not None for value in (source_id, mosque_id, date_from, date_to))


def _occurrence_in_replace_scope(
    occurrence: ScheduleOccurrence,
    *,
    source_id: uuid.UUID | None,
    mosque_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    if not _publish_filters_active(
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
    ):
        return True
    if mosque_id is not None and occurrence.mosque_id != mosque_id:
        return False
    if source_id is not None and occurrence.source_id != source_id:
        return False
    if date_from is not None and occurrence.date < date_from:
        return False
    if date_to is not None and occurrence.date > date_to:
        return False
    return True


async def validate_candidates(
    session: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    source_ids: set[uuid.UUID] | None = None,
    mosque_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    update_status: bool = True,
    settings: Settings | None = None,
) -> ValidateBatchResult:
    cfg = settings or get_settings()
    stmt = select(ScheduleCandidate).where(
        ScheduleCandidate.status.in_(
            (CandidateStatus.PENDING, CandidateStatus.APPROVED),
        )
    )
    if source_ids:
        stmt = stmt.where(ScheduleCandidate.source_id.in_(source_ids))
    stmt = _candidate_filters(
        stmt,
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
    )
    candidates = (await session.execute(stmt)).scalars().all()
    result = ValidateBatchResult()
    context = await build_validation_batch_context(session, list(candidates))

    for candidate in candidates:
        result.examined += 1
        source = context.sources.get(candidate.source_id)
        if source is None:
            result.skipped += 1
            continue
        mosque = (
            context.mosques.get(candidate.mosque_id) if candidate.mosque_id is not None else None
        )
        extraction_kind = context.extraction_kinds.get(candidate.id)
        validation = validate_candidate(
            candidate,
            mosque=mosque,
            source=source,
            duplicate_ids=context.duplicate_ids.get(candidate.id),
            extraction_kind=extraction_kind,
            settings=cfg,
        )
        candidate.validation_errors = validation.to_error_list()

        if not update_status:
            continue

        new_status = status_after_validation(validation, extraction_kind=extraction_kind)
        if new_status == CandidateStatus.APPROVED:
            result.approved += 1
        elif new_status == CandidateStatus.REJECTED:
            result.rejected += 1
        else:
            result.pending += 1
        candidate.status = new_status

    await session.flush()
    return result


async def _load_all_previous_occurrences(
    session: AsyncSession,
    previous_version_id: uuid.UUID | None,
) -> dict[OccurrenceKey, ScheduleOccurrence]:
    if previous_version_id is None:
        return {}

    stmt = (
        select(ScheduleOccurrence)
        .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
        .where(ScheduleOccurrence.dataset_version_id == previous_version_id)
        .where(public_source_filter())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {occurrence_key_from_row(row): row for row in rows}


def _occurrence_changed(
    previous: ScheduleOccurrence | None,
    *,
    jamaat_time: time,
    start_time: time | None,
    session_label: str | None,
    timezone: str,
    source_id: uuid.UUID,
) -> bool:
    if previous is None:
        return True
    return (
        previous.jamaat_time != jamaat_time
        or previous.start_time != start_time
        or previous.session_label != session_label
        or previous.timezone != timezone
        or previous.source_id != source_id
    )


def _copy_carried_occurrence(
    previous: ScheduleOccurrence,
    *,
    dataset_version_id: uuid.UUID,
    now: datetime,
) -> ScheduleOccurrence:
    return ScheduleOccurrence(
        id=uuid.uuid4(),
        mosque_id=previous.mosque_id,
        source_id=previous.source_id,
        candidate_id=previous.candidate_id,
        dataset_version_id=dataset_version_id,
        date=previous.date,
        prayer=previous.prayer,
        start_time=previous.start_time,
        jamaat_time=previous.jamaat_time,
        session_number=previous.session_number,
        session_label=previous.session_label,
        timezone=previous.timezone,
        confidence=previous.confidence,
        freshness_status=previous.freshness_status,
        source_url=previous.source_url,
        last_verified_at=now,
    )


def _removal_payload(previous: ScheduleOccurrence) -> dict[str, str | int]:
    return {
        "prayer": prayer_key(previous.prayer),
        "date": previous.date.isoformat(),
        "session_number": previous.session_number,
        "reason": "not_in_new_publish_set",
    }


async def _select_publishable_candidates(
    session: AsyncSession,
    candidates: list[ScheduleCandidate],
    *,
    settings: Settings,
    result: PublishResult,
) -> list[PublishableCandidate]:
    context = await build_validation_batch_context(session, candidates)
    publishable: list[PublishableCandidate] = []

    for candidate in candidates:
        if candidate.mosque_id is None:
            result.skipped_validation += 1
            continue

        source = context.sources.get(candidate.source_id)
        mosque = context.mosques.get(candidate.mosque_id)
        if source is None or mosque is None:
            result.skipped_validation += 1
            continue

        extraction_kind = context.extraction_kinds.get(candidate.id)
        allowed, reason = can_publish_candidate(
            source, extraction_kind=extraction_kind, settings=settings
        )
        if not allowed:
            result.skipped_policy += 1
            if reason:
                result.errors.append(f"{candidate.id}: {reason}")
            continue

        validation = validate_candidate(
            candidate,
            mosque=mosque,
            source=source,
            duplicate_ids=context.duplicate_ids.get(candidate.id),
            extraction_kind=extraction_kind,
            settings=settings,
        )
        if not validation.is_valid:
            result.skipped_validation += 1
            result.errors.append(f"{candidate.id}: validation failed at publish time")
            continue

        publishable.append(PublishableCandidate(candidate=candidate, source=source, mosque=mosque))

    return publishable


async def _carry_forward_out_of_scope(
    session: AsyncSession,
    *,
    full_previous: dict[OccurrenceKey, ScheduleOccurrence],
    dataset_version: DatasetVersion,
    final_keys: set[OccurrenceKey],
    now: datetime,
    source_id: uuid.UUID | None,
    mosque_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    result: PublishResult,
    touched_sources: set[uuid.UUID],
) -> None:
    for key, previous in full_previous.items():
        if _occurrence_in_replace_scope(
            previous,
            source_id=source_id,
            mosque_id=mosque_id,
            date_from=date_from,
            date_to=date_to,
        ):
            continue
        session.add(
            _copy_carried_occurrence(
                previous,
                dataset_version_id=dataset_version.id,
                now=now,
            )
        )
        final_keys.add(key)
        result.carried_forward += 1
        touched_sources.add(previous.source_id)


async def _emit_removals(
    session: AsyncSession,
    *,
    full_previous: dict[OccurrenceKey, ScheduleOccurrence],
    final_keys: set[OccurrenceKey],
    dataset_version: DatasetVersion,
    result: PublishResult,
) -> None:
    for key, previous in full_previous.items():
        if key in final_keys:
            continue
        session.add(
            ChangeEvent(
                event_type=ChangeEventType.OCCURRENCE_REMOVED,
                mosque_id=previous.mosque_id,
                occurrence_id=previous.id,
                dataset_version_id=dataset_version.id,
                payload=_removal_payload(previous),
            )
        )
        result.removed_occurrences += 1
        result.change_events += 1


async def _publish_batch_rows(
    session: AsyncSession,
    *,
    publishable: list[PublishableCandidate],
    dataset_version: DatasetVersion,
    full_previous: dict[OccurrenceKey, ScheduleOccurrence],
    final_keys: set[OccurrenceKey],
    now: datetime,
    result: PublishResult,
    touched_sources: set[uuid.UUID],
) -> None:
    for item in publishable:
        candidate = item.candidate
        source = item.source
        mosque = item.mosque

        if candidate.jamaat_time is None or candidate.mosque_id is None:
            result.skipped_validation += 1
            continue

        prayer_value = prayer_key(candidate.prayer)
        key = occurrence_key(
            candidate.mosque_id,
            candidate.date,
            candidate.prayer,
            candidate.session_number,
        )
        final_keys.add(key)

        linkback = (candidate.evidence or {}).get("linkback_url")
        source_url = linkback or source.source_url
        previous = full_previous.get(key)
        unchanged = previous is not None and not _occurrence_changed(
            previous,
            jamaat_time=candidate.jamaat_time,
            start_time=candidate.start_time,
            session_label=candidate.session_label,
            timezone=candidate.timezone,
            source_id=source.id,
        )

        if unchanged and previous is not None:
            occurrence = _copy_carried_occurrence(
                previous,
                dataset_version_id=dataset_version.id,
                now=now,
            )
            occurrence.candidate_id = candidate.id
        else:
            occurrence = ScheduleOccurrence(
                id=uuid.uuid4(),
                mosque_id=candidate.mosque_id,
                source_id=source.id,
                candidate_id=candidate.id,
                dataset_version_id=dataset_version.id,
                date=candidate.date,
                prayer=candidate.prayer,
                start_time=candidate.start_time,
                jamaat_time=candidate.jamaat_time,
                session_number=candidate.session_number,
                session_label=candidate.session_label,
                timezone=candidate.timezone,
                confidence=candidate.confidence or source.confidence,
                freshness_status=FreshnessStatus.NEEDS_REVIEW,
                source_url=source_url,
                last_verified_at=now,
            )

        session.add(occurrence)
        await session.flush()

        if not unchanged:
            session.add(
                ChangeEvent(
                    event_type=ChangeEventType.OCCURRENCE_PUBLISHED,
                    mosque_id=mosque.id,
                    occurrence_id=occurrence.id,
                    dataset_version_id=dataset_version.id,
                    payload={
                        "prayer": prayer_value,
                        "date": candidate.date.isoformat(),
                        "session_number": candidate.session_number,
                    },
                )
            )
            result.change_events += 1
        result.published += 1
        candidate.status = CandidateStatus.SUPERSEDED
        touched_sources.add(source.id)


async def publish_candidates(
    session: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    mosque_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    dataset_version: DatasetVersion | None = None,
    settings: Settings | None = None,
) -> PublishResult:
    cfg = settings or get_settings()
    result = PublishResult()

    stmt = select(ScheduleCandidate).where(ScheduleCandidate.status == CandidateStatus.APPROVED)
    stmt = _candidate_filters(
        stmt,
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
    )
    candidates = (await session.execute(stmt)).scalars().all()
    publishable = await _select_publishable_candidates(
        session, list(candidates), settings=cfg, result=result
    )

    if not publishable:
        result.errors.append("no approved candidates matched filters or passed publication gates")
        await session.flush()
        return result

    previous_version = await get_latest_published_version(session)
    previous_id = previous_version.id if previous_version else None
    full_previous = await _load_all_previous_occurrences(session, previous_id)

    if dataset_version is None:
        dataset_version = await create_published_dataset_version(session)

    result.dataset_version = dataset_version.version
    final_keys: set[OccurrenceKey] = set()
    touched_sources: set[uuid.UUID] = set()
    now = datetime.now(UTC)
    partial_publish = _publish_filters_active(
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
    )

    if partial_publish:
        await _carry_forward_out_of_scope(
            session,
            full_previous=full_previous,
            dataset_version=dataset_version,
            final_keys=final_keys,
            now=now,
            source_id=source_id,
            mosque_id=mosque_id,
            date_from=date_from,
            date_to=date_to,
            result=result,
            touched_sources=touched_sources,
        )

    await _publish_batch_rows(
        session,
        publishable=publishable,
        dataset_version=dataset_version,
        full_previous=full_previous,
        final_keys=final_keys,
        now=now,
        result=result,
        touched_sources=touched_sources,
    )
    await _emit_removals(
        session,
        full_previous=full_previous,
        final_keys=final_keys,
        dataset_version=dataset_version,
        result=result,
    )

    manifest = dict(dataset_version.manifest or {})
    manifest.update(
        {
            "occurrences_published": result.published,
            "occurrences_carried_forward": result.carried_forward,
            "occurrences_removed": result.removed_occurrences,
            "sources_touched": len(touched_sources),
        }
    )
    dataset_version.manifest = manifest

    for src_id in touched_sources:
        await recompute_source_health(session, src_id, settings=cfg)
        await refresh_occurrence_freshness_for_source(session, src_id)

    await session.flush()
    return result
