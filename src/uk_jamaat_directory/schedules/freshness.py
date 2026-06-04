from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import FreshnessStatus, Prayer
from uk_jamaat_directory.models.core import (
    MosqueSource,
    ScheduleOccurrence,
    SourceHealth,
)
from uk_jamaat_directory.schedules.dataset import get_latest_published_version
from uk_jamaat_directory.services.public_policy import public_source_filter

DAILY_PRAYERS = (
    Prayer.FAJR,
    Prayer.DHUHR,
    Prayer.ASR,
    Prayer.MAGHRIB,
    Prayer.ISHA,
)


def _today_london() -> date:
    return datetime.now(ZoneInfo("Europe/London")).date()


def expected_prayers_for_date(on_date: date) -> set[Prayer]:
    prayers = set(DAILY_PRAYERS)
    if on_date.weekday() == 4:
        prayers.add(Prayer.JUMUAH)
    return prayers


async def _published_occurrence_keys(
    session: AsyncSession,
    *,
    mosque_id: uuid.UUID,
    source_id: uuid.UUID,
    date_from: date,
    date_to: date,
    dataset_version_id: uuid.UUID | None,
) -> set[tuple[date, Prayer]]:
    stmt = (
        select(ScheduleOccurrence.date, ScheduleOccurrence.prayer)
        .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
        .where(ScheduleOccurrence.mosque_id == mosque_id)
        .where(ScheduleOccurrence.source_id == source_id)
        .where(ScheduleOccurrence.date >= date_from)
        .where(ScheduleOccurrence.date <= date_to)
        .where(public_source_filter())
    )
    if dataset_version_id is not None:
        stmt = stmt.where(ScheduleOccurrence.dataset_version_id == dataset_version_id)

    rows = (await session.execute(stmt)).all()
    return {(row[0], row[1]) for row in rows}


def _coverage_days_with_all_prayers(
    keys: set[tuple[date, Prayer]],
    *,
    start: date,
    end: date,
) -> int:
    count = 0
    current = start
    while current <= end:
        expected = expected_prayers_for_date(current)
        present = {prayer for day, prayer in keys if day == current}
        if expected.issubset(present):
            count += 1
        current += timedelta(days=1)
    return count


def classify_source_freshness(
    *,
    today: date,
    keys: set[tuple[date, Prayer]],
    last_success_at: datetime | None,
    consecutive_failures: int,
    settings: Settings | None = None,
) -> tuple[FreshnessStatus, int, str]:
    cfg = settings or get_settings()
    if consecutive_failures >= 3:
        return FreshnessStatus.SOURCE_FAILED, 0, "three or more consecutive source failures"

    window_end = today + timedelta(days=7)
    coverage = _coverage_days_with_all_prayers(keys, start=today, end=window_end)

    if last_success_at is not None:
        stale_cutoff = datetime.now(UTC) - timedelta(days=cfg.freshness_stale_days)
        if last_success_at < stale_cutoff:
            return FreshnessStatus.STALE, coverage, "source not refreshed within stale threshold"

    today_expected = expected_prayers_for_date(today)
    today_present = {prayer for day, prayer in keys if day == today}
    if not today_expected.issubset(today_present):
        return FreshnessStatus.MISSING_TODAY, coverage, "incomplete prayer coverage for today"

    days_needed = 8
    if coverage < days_needed:
        return (
            FreshnessStatus.MISSING_NEXT_7_DAYS,
            coverage,
            "incomplete coverage for today and the next 7 days",
        )

    return FreshnessStatus.FRESH, coverage, "published schedule coverage is current"


def classify_occurrence_freshness(
    source_freshness: FreshnessStatus,
) -> FreshnessStatus:
    if source_freshness == FreshnessStatus.FRESH:
        return FreshnessStatus.FRESH
    if source_freshness in (
        FreshnessStatus.MISSING_TODAY,
        FreshnessStatus.MISSING_NEXT_7_DAYS,
    ):
        return source_freshness
    if source_freshness == FreshnessStatus.STALE:
        return FreshnessStatus.STALE
    if source_freshness == FreshnessStatus.SOURCE_FAILED:
        return FreshnessStatus.SOURCE_FAILED
    return FreshnessStatus.NEEDS_REVIEW


async def recompute_source_health(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    settings: Settings | None = None,
) -> SourceHealth:
    cfg = settings or get_settings()
    source = await session.get(MosqueSource, source_id)
    if source is None or source.mosque_id is None:
        msg = f"source not found or not linked: {source_id}"
        raise ValueError(msg)

    health = await session.get(SourceHealth, source_id)
    if health is None:
        health = SourceHealth(source_id=source_id)
        session.add(health)

    today = _today_london()
    latest_version = await get_latest_published_version(session)
    version_id = latest_version.id if latest_version else None

    keys = await _published_occurrence_keys(
        session,
        mosque_id=source.mosque_id,
        source_id=source_id,
        date_from=today - timedelta(days=1),
        date_to=today + timedelta(days=7),
        dataset_version_id=version_id,
    )

    status, coverage, message = classify_source_freshness(
        today=today,
        keys=keys,
        last_success_at=health.last_success_at,
        consecutive_failures=health.consecutive_failures,
        settings=cfg,
    )
    health.freshness_status = status
    health.next_7_days_coverage = coverage
    health.message = message
    await session.flush()
    return health


async def recompute_all_source_health(session: AsyncSession) -> int:
    source_ids = (
        await session.execute(
            select(MosqueSource.id)
            .where(MosqueSource.mosque_id.is_not(None))
            .where(public_source_filter())
        )
    ).scalars().all()

    count = 0
    for source_id in source_ids:
        await recompute_source_health(session, source_id)
        count += 1
    return count


async def refresh_occurrence_freshness_for_source(
    session: AsyncSession,
    source_id: uuid.UUID,
) -> int:
    health = await session.get(SourceHealth, source_id)
    if health is None:
        return 0

    occ_status = classify_occurrence_freshness(health.freshness_status)
    stmt = (
        select(ScheduleOccurrence)
        .where(ScheduleOccurrence.source_id == source_id)
        .where(ScheduleOccurrence.dataset_version_id.is_not(None))
    )
    occurrences = (await session.execute(stmt)).scalars().all()
    updated = 0
    for occurrence in occurrences:
        if occurrence.freshness_status != occ_status:
            occurrence.freshness_status = occ_status
            updated += 1
    await session.flush()
    return updated
