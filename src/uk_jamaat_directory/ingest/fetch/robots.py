from __future__ import annotations

from urllib import robotparser
from urllib.parse import urlparse

import httpx

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.fetch.client import build_http_client

_robots_cache: dict[str, robotparser.RobotFileParser | None] = {}


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


async def _load_robots(
    url: str, settings: Settings | None = None
) -> robotparser.RobotFileParser | None:
    domain = urlparse(url).netloc.lower()
    if domain in _robots_cache:
        return _robots_cache[domain]

    robots_url = _robots_url(url)
    cfg = settings or get_settings()
    parser = robotparser.RobotFileParser()
    parser.set_url(robots_url)

    try:
        async with build_http_client(cfg) as client:
            response = await client.get(robots_url)
            if response.status_code >= 400:
                _robots_cache[domain] = None
                return None
            parser.parse(response.text.splitlines())
    except httpx.HTTPError:
        _robots_cache[domain] = None
        return None

    _robots_cache[domain] = parser
    return parser


async def can_fetch(url: str, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    parser = await _load_robots(url, cfg)
    if parser is None:
        return True
    return parser.can_fetch(cfg.crawl_user_agent, url)


def clear_robots_cache() -> None:
    _robots_cache.clear()
