from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status

from uk_jamaat_directory.config import Settings, get_settings


@dataclass
class _RateLimitBucket:
    timestamps: list[float] = field(default_factory=list)


_buckets: dict[str, _RateLimitBucket] = defaultdict(_RateLimitBucket)


def _client_key(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


async def limit_community_submissions(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.community_submission_rate_limit <= 0:
        return

    key = _client_key(request)
    bucket = _buckets[key]
    now = time.monotonic()
    window = settings.community_submission_rate_window_seconds
    bucket.timestamps = [stamp for stamp in bucket.timestamps if now - stamp < window]
    if len(bucket.timestamps) >= settings.community_submission_rate_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many mosque submissions. Please try again later.",
        )
    bucket.timestamps.append(now)
