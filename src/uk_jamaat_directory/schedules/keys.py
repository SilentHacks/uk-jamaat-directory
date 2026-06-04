from __future__ import annotations

import uuid
from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.models.core import ScheduleCandidate, ScheduleOccurrence

OccurrenceKey = tuple[uuid.UUID, date, str, int]


def prayer_key(prayer: Prayer | str) -> str:
    if isinstance(prayer, Prayer):
        return prayer.value
    return str(prayer)


def occurrence_key(
    mosque_id: uuid.UUID,
    on_date: date,
    prayer: Prayer | str,
    session_number: int,
) -> OccurrenceKey:
    return (mosque_id, on_date, prayer_key(prayer), session_number)


def occurrence_key_from_candidate(candidate: ScheduleCandidate) -> OccurrenceKey | None:
    if candidate.mosque_id is None:
        return None
    return occurrence_key(
        candidate.mosque_id,
        candidate.date,
        candidate.prayer,
        candidate.session_number,
    )


def occurrence_key_from_row(row: ScheduleOccurrence) -> OccurrenceKey:
    return occurrence_key(row.mosque_id, row.date, row.prayer, row.session_number)
