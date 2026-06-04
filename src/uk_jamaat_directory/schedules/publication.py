from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import CandidateStatus, ChangeEventType
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
    classify_occurrence_freshness,
    recompute_source_health,
    refresh_occurrence_freshness_for_source,
)
from uk_jamaat_directory.schedules.gates import can_publish_candidate
from uk_jamaat_directory.schedules.types import PublishResult, ValidateBatchResult
from uk_jamaat_directory.schedules.validation import (
    find_duplicate_candidate_ids,
    resolve_extraction_kind,
    status_after_validation,
    validate_candidate,
)
from uk_jamaat_directory.services.public_policy import public_source_filter

OccurrenceKey = tuple[uuid.UUID, date, str, int]


def _occurrence_key(
    mosque_id: uuid.UUID,
    on_date: date,
    prayer: str,
    session_number: int,
) -> OccurrenceKey:
    return (mosque_id, on_date, prayer, session_number)


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


async def validate_candidates(
    session: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
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
    stmt = _candidate_filters(
        stmt,
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
    )
    candidates = (await session.execute(stmt)).scalars().all()
    result = ValidateBatchResult()

    for candidate in candidates:
        result.examined += 1
        source = await session.get(MosqueSource, candidate.source_id)
        if source is None:
            result.skipped += 1
            continue
        mosque = (
            await session.get(Mosque, candidate.mosque_id) if candidate.mosque_id else None
        )
        dupes = await find_duplicate_candidate_ids(session, candidate)
        extraction_kind = await resolve_extraction_kind(session, candidate)
        validation = validate_candidate(
            candidate,
            mosque=mosque,
            source=source,
            duplicate_ids=dupes,
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


async def _load_previous_occurrences(
    session: AsyncSession,
    previous_version_id: uuid.UUID | None,
    mosque_ids: set[uuid.UUID],
) -> dict[OccurrenceKey, ScheduleOccurrence]:
    if previous_version_id is None or not mosque_ids:
        return {}

    stmt = (
        select(ScheduleOccurrence)
        .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
        .where(ScheduleOccurrence.dataset_version_id == previous_version_id)
        .where(ScheduleOccurrence.mosque_id.in_(mosque_ids))
        .where(public_source_filter())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return {
        _occurrence_key(
            row.mosque_id,
            row.date,
            row.prayer.value if hasattr(row.prayer, "value") else str(row.prayer),
            row.session_number,
        ): row
        for row in rows
    }


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

    mosque_ids: set[uuid.UUID] = set()
    to_publish: list[tuple[ScheduleCandidate, MosqueSource, Mosque]] = []

    for candidate in candidates:
        if candidate.mosque_id is None:
            result.skipped_validation += 1
            continue

        source = await session.get(MosqueSource, candidate.source_id)
        mosque = await session.get(Mosque, candidate.mosque_id)
        if source is None or mosque is None:
            result.skipped_validation += 1
            continue

        extraction_kind = await resolve_extraction_kind(session, candidate)
        allowed, reason = can_publish_candidate(
            source, extraction_kind=extraction_kind, settings=cfg
        )
        if not allowed:
            result.skipped_policy += 1
            if reason:
                result.errors.append(f"{candidate.id}: {reason}")
            continue

        dupes = await find_duplicate_candidate_ids(session, candidate)
        validation = validate_candidate(
            candidate,
            mosque=mosque,
            source=source,
            duplicate_ids=dupes,
            extraction_kind=extraction_kind,
            settings=cfg,
        )
        if not validation.is_valid:
            result.skipped_validation += 1
            result.errors.append(f"{candidate.id}: validation failed at publish time")
            continue

        to_publish.append((candidate, source, mosque))
        mosque_ids.add(mosque.id)

    if not to_publish:
        result.errors.append("no approved candidates matched filters or passed publication gates")
        await session.flush()
        return result

    previous_version = await get_latest_published_version(session)
    previous_id = previous_version.id if previous_version else None

    if dataset_version is None:
        dataset_version = await create_published_dataset_version(session)

    result.dataset_version = dataset_version.version

    previous_map = await _load_previous_occurrences(session, previous_id, mosque_ids)
    new_keys: set[OccurrenceKey] = set()
    touched_sources: set[uuid.UUID] = set()
    now = datetime.now(UTC)

    for candidate, source, mosque in to_publish:
        if candidate.jamaat_time is None or candidate.mosque_id is None:
            result.skipped_validation += 1
            continue

        prayer_value = (
            candidate.prayer.value
            if hasattr(candidate.prayer, "value")
            else str(candidate.prayer)
        )
        key = _occurrence_key(
            candidate.mosque_id, candidate.date, prayer_value, candidate.session_number
        )
        new_keys.add(key)

        health = await recompute_source_health(session, source.id, settings=cfg)
        occ_freshness = classify_occurrence_freshness(health.freshness_status)

        linkback = (candidate.evidence or {}).get("linkback_url")
        source_url = linkback or source.source_url

        previous = previous_map.get(key)
        unchanged = previous is not None and not _occurrence_changed(
            previous,
            jamaat_time=candidate.jamaat_time,
            start_time=candidate.start_time,
            session_label=candidate.session_label,
            timezone=candidate.timezone,
            source_id=source.id,
        )

        if unchanged and previous is not None:
            occurrence = ScheduleOccurrence(
                id=uuid.uuid4(),
                mosque_id=previous.mosque_id,
                source_id=previous.source_id,
                candidate_id=candidate.id,
                dataset_version_id=dataset_version.id,
                date=previous.date,
                prayer=previous.prayer,
                start_time=previous.start_time,
                jamaat_time=previous.jamaat_time,
                session_number=previous.session_number,
                session_label=previous.session_label,
                timezone=previous.timezone,
                confidence=previous.confidence,
                freshness_status=occ_freshness,
                source_url=previous.source_url,
                last_verified_at=now,
            )
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
                freshness_status=occ_freshness,
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

    for key, previous in previous_map.items():
        if key not in new_keys:
            session.add(
                ChangeEvent(
                    event_type=ChangeEventType.OCCURRENCE_REMOVED,
                    mosque_id=previous.mosque_id,
                    occurrence_id=previous.id,
                    dataset_version_id=dataset_version.id,
                    payload={
                        "prayer": previous.prayer.value
                        if hasattr(previous.prayer, "value")
                        else str(previous.prayer),
                        "date": previous.date.isoformat(),
                        "session_number": previous.session_number,
                        "reason": "not_in_new_publish_set",
                    },
                )
            )
            result.removed_occurrences += 1
            result.change_events += 1

    manifest = dict(dataset_version.manifest or {})
    manifest.update(
        {
            "occurrences_published": result.published,
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
