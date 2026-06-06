from __future__ import annotations

import httpx
import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.fetch.robots import clear_robots_cache
from uk_jamaat_directory.ingest.fetch.security import (
    ensure_resolvable_public_host,
    validate_fetch_url,
)
from uk_jamaat_directory.ingest.fetch.service import fetch_url
from uk_jamaat_directory.ingest.fetch.throttle import clear_domain_throttle


@pytest.fixture(autouse=True)
def _clear_fetch_state() -> None:
    clear_robots_cache()
    clear_domain_throttle()


def test_validate_fetch_url_blocks_loopback_literal() -> None:
    assert validate_fetch_url("http://127.0.0.1/feed.json") == "blocked host address"


@pytest.mark.asyncio
async def test_fetch_url_blocks_loopback_without_network() -> None:
    settings = Settings(
        environment="test", crawl_user_agent="TestBot", crawl_per_domain_delay_seconds=0
    )
    result = await fetch_url(
        "http://127.0.0.1/prayer-times.json", settings=settings
    )
    assert result.error == "blocked host address"
    assert not result.ok


@pytest.mark.asyncio
async def test_fetch_url_blocks_redirect_to_private_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "example.org":
            return httpx.Response(
                302,
                headers={"Location": "http://127.0.0.1/private.json"},
            )
        return httpx.Response(200, text='{"times": []}')

    transport = httpx.MockTransport(handler)
    settings = Settings(
        environment="test", crawl_user_agent="TestBot", crawl_per_domain_delay_seconds=0
    )

    import uk_jamaat_directory.ingest.fetch.client as client_module
    import uk_jamaat_directory.ingest.fetch.robots as robots_module
    import uk_jamaat_directory.ingest.fetch.service as service_module

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    def patched_build(_settings=None):
        return PatchedClient(
            timeout=settings.crawl_timeout_seconds,
            headers={"User-Agent": settings.crawl_user_agent},
            follow_redirects=False,
        )

    old_client_build = client_module.build_http_client
    old_robots_build = robots_module.build_http_client
    old_service_build = service_module.build_http_client
    client_module.build_http_client = patched_build
    robots_module.build_http_client = patched_build
    service_module.build_http_client = patched_build
    try:
        result = await fetch_url(
            "https://example.org/prayer-times.html",
            settings=settings,
        )
    finally:
        client_module.build_http_client = old_client_build
        robots_module.build_http_client = old_robots_build
        service_module.build_http_client = old_service_build

    assert result.error == "blocked host address"
    assert not result.ok


@pytest.mark.asyncio
async def test_fetch_url_rejects_oversized_response() -> None:
    max_bytes = 32

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"x" * (max_bytes + 1))

    transport = httpx.MockTransport(handler)
    settings = Settings(
        environment="test",
        crawl_user_agent="TestBot",
        crawl_max_bytes=max_bytes,
        crawl_per_domain_delay_seconds=0,
    )

    import uk_jamaat_directory.ingest.fetch.client as client_module
    import uk_jamaat_directory.ingest.fetch.robots as robots_module
    import uk_jamaat_directory.ingest.fetch.service as service_module

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    def patched_build(_settings=None):
        return PatchedClient(
            timeout=settings.crawl_timeout_seconds,
            headers={"User-Agent": settings.crawl_user_agent},
            follow_redirects=False,
        )

    old_client_build = client_module.build_http_client
    old_robots_build = robots_module.build_http_client
    old_service_build = service_module.build_http_client
    client_module.build_http_client = patched_build
    robots_module.build_http_client = patched_build
    service_module.build_http_client = patched_build
    try:
        result = await fetch_url(
            "https://example.org/prayer-times.html",
            settings=settings,
        )
    finally:
        client_module.build_http_client = old_client_build
        robots_module.build_http_client = old_robots_build
        service_module.build_http_client = old_service_build

    assert result.error == f"response exceeds max bytes ({max_bytes})"
    assert not result.ok


@pytest.mark.asyncio
async def test_ensure_resolvable_public_host_blocks_private_dns() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "uk_jamaat_directory.ingest.fetch.security.socket.getaddrinfo",
            lambda hostname, port, family=0, type=0, proto=0, flags=0: [
                (2, 1, 6, "", ("127.0.0.1", 0))
            ],
        )
        blocked = await ensure_resolvable_public_host(
            "https://example.org/prayer-times.html"
        )

    assert blocked == "blocked host address"
