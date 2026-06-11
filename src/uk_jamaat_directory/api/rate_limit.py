from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, Response, status

from uk_jamaat_directory.config import Settings, get_settings


@dataclass
class _RateLimitBucket:
    timestamps: list[float] = field(default_factory=list)


class SlidingWindowLimiter:
    """In-memory per-key sliding-window limiter.

    Exact for a single process (the production topology: one uvicorn process on one
    VPS). If the API is ever scaled to multiple workers or instances this must move
    to a shared store (see ADR 0019).
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _RateLimitBucket] = defaultdict(_RateLimitBucket)

    def check(self, key: str, limit: int, window_seconds: float) -> bool:
        """Record a hit for ``key``; return True if allowed, False if over the limit."""
        if limit <= 0:
            return True
        bucket = self._buckets[key]
        now = time.monotonic()
        bucket.timestamps = [ts for ts in bucket.timestamps if now - ts < window_seconds]
        if len(bucket.timestamps) >= limit:
            return False
        bucket.timestamps.append(now)
        return True

    def reset(self) -> None:
        self._buckets.clear()


# Distinct limiters so the strict submission gate and the broad public limit do not
# share buckets.
_submission_limiter = SlidingWindowLimiter()
_public_limiter = SlidingWindowLimiter()


def _client_key(request: Request) -> str:
    if request.client is not None:
        return request.client.host
    return "unknown"


async def limit_community_submissions(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    allowed = _submission_limiter.check(
        _client_key(request),
        settings.community_submission_rate_limit,
        settings.community_submission_rate_window_seconds,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many mosque submissions. Please try again later.",
        )


async def public_rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Global per-IP limit on all public API traffic; health checks are exempt."""
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    path = request.url.path
    exempt = path.endswith("/health") or path.endswith("/health/ready")
    if not exempt:
        allowed = _public_limiter.check(
            _client_key(request),
            settings.public_rate_limit,
            settings.public_rate_window_seconds,
        )
        if not allowed:
            return Response(
                content='{"error":{"code":"rate_limited",'
                '"message":"Rate limit exceeded. Please slow down."}}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
                headers={"Retry-After": str(settings.public_rate_window_seconds)},
            )
    return await call_next(request)
