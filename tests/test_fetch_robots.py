from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.fetch.robots import clear_robots_cache
from uk_jamaat_directory.ingest.fetch.service import fetch_url
from uk_jamaat_directory.ingest.fetch.throttle import clear_domain_throttle

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/crawl"


@pytest.fixture(autouse=True)
def _clear_robots() -> None:
    clear_robots_cache()
    clear_domain_throttle()


@pytest.mark.asyncio
async def test_fetch_url_reports_robots_error() -> None:
    robots_body = (FIXTURES / "robots_disallow.txt").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_body)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    settings = Settings(
        environment="test",
        crawl_user_agent="TestBot",
        allowed_hosts=["test"],
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
            "https://example.org/.well-known/uk-jamaat-directory.json",
            settings=settings,
        )
    finally:
        client_module.build_http_client = old_client_build
        robots_module.build_http_client = old_robots_build
        service_module.build_http_client = old_service_build
        clear_robots_cache()

    assert result.error == "robots.txt disallows fetch"
    assert not result.ok
