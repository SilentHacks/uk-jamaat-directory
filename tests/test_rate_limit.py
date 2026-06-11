from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from uk_jamaat_directory.api import rate_limit
from uk_jamaat_directory.config import Settings


@pytest.mark.asyncio
async def test_community_submission_rate_limit_blocks_burst() -> None:
    rate_limit._submission_limiter.reset()
    settings = Settings(
        community_submission_rate_limit=2, community_submission_rate_window_seconds=60
    )
    request = MagicMock()
    request.client = MagicMock(host="10.0.0.1")

    await rate_limit.limit_community_submissions(request, settings=settings)
    await rate_limit.limit_community_submissions(request, settings=settings)

    with pytest.raises(HTTPException) as exc_info:
        await rate_limit.limit_community_submissions(request, settings=settings)
    assert exc_info.value.status_code == 429


def test_sliding_window_expires_old_hits() -> None:
    limiter = rate_limit.SlidingWindowLimiter()
    # First hit at limit=1 is allowed; an immediate second is blocked.
    assert limiter.check("k", limit=1, window_seconds=60) is True
    assert limiter.check("k", limit=1, window_seconds=60) is False
    # With a window already elapsed, the bucket clears and the hit is allowed again.
    limiter._buckets["k"].timestamps = [time.monotonic() - 2]
    assert limiter.check("k", limit=1, window_seconds=1) is True


def test_sliding_window_disabled_when_limit_non_positive() -> None:
    limiter = rate_limit.SlidingWindowLimiter()
    for _ in range(100):
        assert limiter.check("k", limit=0, window_seconds=60) is True
