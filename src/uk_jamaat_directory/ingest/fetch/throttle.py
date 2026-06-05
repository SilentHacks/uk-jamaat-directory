from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse

from uk_jamaat_directory.config import Settings

_domain_last_fetch: dict[str, float] = {}
_domain_locks: dict[str, asyncio.Lock] = {}


async def wait_for_domain(url: str, settings: Settings) -> None:
    delay = settings.crawl_per_domain_delay_seconds
    if delay <= 0:
        return

    domain = urlparse(url).netloc.lower()
    lock = _domain_locks.setdefault(domain, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        last_fetch = _domain_last_fetch.get(domain, 0.0)
        wait_seconds = delay - (now - last_fetch)
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        _domain_last_fetch[domain] = time.monotonic()


def clear_domain_throttle() -> None:
    _domain_last_fetch.clear()
