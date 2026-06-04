from __future__ import annotations

import uuid
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import MyLocalMasjidScheduleRow
from uk_jamaat_directory.models.core import Mosque, MosqueSource, ScheduleCandidate


def _times_equal(left: time | None, right: time | None) -> bool:
    return left == right


def _candidate_unchanged(
    existing: ScheduleCandidate,
    *,
    start_time: time | None,
    jamaat_time: time,
    session_label: str | None,
    timezone: str,
    extraction_run_id: uuid.UUID,
) -> bool:
    return (
        _times_equal(existing.start_time, start_time)
        and existing.jamaat_time == jamaat_time
        and existing.session_label == session_label
        and existing.timezone == timezone
        and existing.extraction_run_id == extraction_run_id
    )


async def upsert_schedule_candidate(
    session: AsyncSession,
    *,
    mosque: Mosque,
    source: MosqueSource,
    extraction_run_id: uuid.UUID,
    row: MyLocalMasjidScheduleRow,
    jamaat_time: time,
    start_time: time | None,
) -> tuple[bool, bool]:
    """Return (created_or_updated, skipped_unchanged)."""
    stmt = (
        select(ScheduleCandidate)
        .where(ScheduleCandidate.mosque_id == mosque.id)
        .where(ScheduleCandidate.source_id == source.id)
        .where(ScheduleCandidate.date == row.date)
        .where(ScheduleCandidate.prayer == row.prayer)
        .where(ScheduleCandidate.session_number == row.session_number)
        .where(
            ScheduleCandidate.status.in_(
                (CandidateStatus.PENDING, CandidateStatus.APPROVED),
            )
        )
        .order_by(ScheduleCandidate.updated_at.desc())
        .limit(1)
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    evidence = {
        "source_type": source.source_type.value,
        "external_id": source.external_id,
        "linkback_url": source.metadata_.get("linkback_url"),
    }

    if existing is not None:
        if _candidate_unchanged(
            existing,
            start_time=start_time,
            jamaat_time=jamaat_time,
            session_label=row.session_label,
            timezone=row.timezone,
            extraction_run_id=extraction_run_id,
        ):
            return False, True

        if existing.extraction_run_id != extraction_run_id:
            existing.status = CandidateStatus.SUPERSEDED
            await session.flush()
            existing = None
        else:
            existing.start_time = start_time
            existing.jamaat_time = jamaat_time
            existing.session_label = row.session_label
            existing.timezone = row.timezone
            existing.extraction_run_id = extraction_run_id
            existing.evidence = evidence
            existing.validation_errors = []
            if existing.status == CandidateStatus.APPROVED:
                existing.status = CandidateStatus.PENDING
            await session.flush()
            return True, False

    if existing is None:
        candidate = ScheduleCandidate(
            id=uuid.uuid4(),
            mosque_id=mosque.id,
            source_id=source.id,
            extraction_run_id=extraction_run_id,
            date=row.date,
            prayer=row.prayer,
            start_time=start_time,
            jamaat_time=jamaat_time,
            session_number=row.session_number,
            session_label=row.session_label,
            timezone=row.timezone,
            confidence=source.confidence,
            status=CandidateStatus.PENDING,
            evidence=evidence,
        )
        session.add(candidate)
        await session.flush()
        return True, False

    return False, True
