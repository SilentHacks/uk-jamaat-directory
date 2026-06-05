from __future__ import annotations

import httpx

from uk_jamaat_directory.config import Settings, get_settings


def build_http_client(settings: Settings | None = None) -> httpx.AsyncClient:
    cfg = settings or get_settings()
    timeout = httpx.Timeout(cfg.crawl_timeout_seconds)
    headers = {"User-Agent": cfg.crawl_user_agent}
    return httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True)
