from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from uk_jamaat_directory.api import rate_limit
from uk_jamaat_directory.config import Settings


@pytest.mark.asyncio
async def test_community_submission_rate_limit_blocks_burst() -> None:
    rate_limit._buckets.clear()
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


def test_rate_limit_window_expires() -> None:
    rate_limit._buckets.clear()
    settings = Settings(
        community_submission_rate_limit=1, community_submission_rate_window_seconds=1
    )
    bucket = rate_limit._buckets["test-key"]
    bucket.timestamps = [time.monotonic() - 2]
    now = time.monotonic()
    bucket.timestamps = [
        stamp
        for stamp in bucket.timestamps
        if now - stamp < settings.community_submission_rate_window_seconds
    ]
    assert bucket.timestamps == []
