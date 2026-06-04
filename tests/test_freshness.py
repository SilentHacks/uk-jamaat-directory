from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    FreshnessStatus,
    Prayer,
)
from uk_jamaat_directory.schedules.freshness import (
    classify_source_freshness,
    expected_prayers_for_date,
    recompute_source_health,
)


def test_expected_prayers_includes_jumuah_on_friday() -> None:
    friday = date(2026, 6, 5)
    prayers = expected_prayers_for_date(friday)
    assert Prayer.JUMUAH in prayers
    assert len(prayers) == 6


def test_classify_missing_today() -> None:
    today = date.today()
    status, coverage, _ = classify_source_freshness(
        today=today,
        keys=set(),
        last_success_at=datetime.now(UTC),
        consecutive_failures=0,
    )
    assert status == FreshnessStatus.MISSING_TODAY
    assert coverage == 0


@pytest.mark.asyncio
async def test_recompute_source_health_after_publish(db_session: AsyncSession) -> None:
    from fixtures import seed_public_mosque_bundle

    bundle = await seed_public_mosque_bundle(db_session)
    source = bundle["public_source"]
    health = await recompute_source_health(db_session, source.id)
    assert health.freshness_status in (
        FreshnessStatus.FRESH,
        FreshnessStatus.MISSING_TODAY,
        FreshnessStatus.MISSING_NEXT_7_DAYS,
    )
