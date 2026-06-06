from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.fetch.robots import clear_robots_cache
from uk_jamaat_directory.ingest.fetch.service import fetch_url
from uk_jamaat_directory.ingest.fetch.throttle import clear_domain_throttle
from uk_jamaat_directory.models.core import SourceArtifact


@pytest.fixture(autouse=True)
def _clear_robots() -> None:
    clear_robots_cache()
    clear_domain_throttle()


@pytest.mark.asyncio
async def test_fetch_returns_304_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.headers.get("If-None-Match") == '"abc"':
            return httpx.Response(304, headers={"ETag": '"abc"'})
        return httpx.Response(200, text='{"times": []}', headers={"ETag": '"abc"'})

    transport = httpx.MockTransport(handler)
    settings = Settings(
        environment="test",
        crawl_user_agent="TestBot",
        allowed_hosts=["test"],
        crawl_per_domain_delay_seconds=0,
    )
    prior = SourceArtifact(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        fetched_url="https://example.org/prayer-times.json",
        etag='"abc"',
        fetched_at=datetime.now(UTC),
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
        result = await fetch_url(prior.fetched_url, prior_artifact=prior, settings=settings)
    finally:
        client_module.build_http_client = old_client_build
        robots_module.build_http_client = old_robots_build
        service_module.build_http_client = old_service_build
        clear_robots_cache()

    assert result.unchanged is True
    assert result.status_code == 304
    assert result.ok
