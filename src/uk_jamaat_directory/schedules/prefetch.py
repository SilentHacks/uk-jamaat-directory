from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import ExtractionKind
from uk_jamaat_directory.models.core import ExtractionRun, Mosque, MosqueSource, ScheduleCandidate
from uk_jamaat_directory.schedules.validation import ACTIVE_CANDIDATE_STATUSES


@dataclass
class ValidationBatchContext:
    sources: dict[uuid.UUID, MosqueSource]
    mosques: dict[uuid.UUID, Mosque]
    extraction_kinds: dict[uuid.UUID, ExtractionKind | None]
    duplicate_ids: dict[uuid.UUID, set[uuid.UUID]]


def _natural_key(candidate: ScheduleCandidate) -> tuple | None:
    if candidate.mosque_id is None:
        return None
    return (
        candidate.mosque_id,
        candidate.source_id,
        candidate.date,
        candidate.prayer,
        candidate.session_number,
    )


async def build_validation_batch_context(
    session: AsyncSession,
    candidates: list[ScheduleCandidate],
) -> ValidationBatchContext:
    if not candidates:
        return ValidationBatchContext({}, {}, {}, {})

    source_ids = {candidate.source_id for candidate in candidates}
    mosque_ids = {
        candidate.mosque_id for candidate in candidates if candidate.mosque_id is not None
    }
    run_ids = {
        candidate.extraction_run_id
        for candidate in candidates
        if candidate.extraction_run_id is not None
    }

    sources = {
        row.id: row
        for row in (
            await session.execute(select(MosqueSource).where(MosqueSource.id.in_(source_ids)))
        ).scalars()
    }
    mosques = (
        {
            row.id: row
            for row in (
                await session.execute(select(Mosque).where(Mosque.id.in_(mosque_ids)))
            ).scalars()
        }
        if mosque_ids
        else {}
    )

    run_kinds: dict[uuid.UUID, ExtractionKind] = {}
    if run_ids:
        runs = (
            await session.execute(select(ExtractionRun).where(ExtractionRun.id.in_(run_ids)))
        ).scalars()
        run_kinds = {run.id: run.kind for run in runs}

    extraction_kinds: dict[uuid.UUID, ExtractionKind | None] = {}
    for candidate in candidates:
        if candidate.extraction_run_id is None:
            extraction_kinds[candidate.id] = None
        else:
            extraction_kinds[candidate.id] = run_kinds.get(candidate.extraction_run_id)

    duplicate_ids = await _build_duplicate_map(session, candidates)
    return ValidationBatchContext(
        sources=sources,
        mosques=mosques,
        extraction_kinds=extraction_kinds,
        duplicate_ids=duplicate_ids,
    )


async def _build_duplicate_map(
    session: AsyncSession,
    candidates: list[ScheduleCandidate],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    mosque_ids = {candidate.mosque_id for candidate in candidates if candidate.mosque_id}
    if not mosque_ids:
        return {candidate.id: set() for candidate in candidates}

    active = (
        (
            await session.execute(
                select(ScheduleCandidate)
                .where(ScheduleCandidate.mosque_id.in_(mosque_ids))
                .where(ScheduleCandidate.status.in_(ACTIVE_CANDIDATE_STATUSES))
            )
        )
        .scalars()
        .all()
    )

    by_key: dict[tuple, list[uuid.UUID]] = defaultdict(list)
    for row in active:
        key = _natural_key(row)
        if key is not None:
            by_key[key].append(row.id)

    return {
        candidate.id: set(by_key.get(_natural_key(candidate) or (), [])) - {candidate.id}
        for candidate in candidates
    }
