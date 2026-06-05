from __future__ import annotations

import httpx

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.fetch.client import build_http_client
from uk_jamaat_directory.ingest.fetch.conditional import conditional_headers
from uk_jamaat_directory.ingest.fetch.robots import can_fetch
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import SourceArtifact


async def fetch_url(
    url: str,
    *,
    prior_artifact: SourceArtifact | None = None,
    settings: Settings | None = None,
) -> FetchResult:
    cfg = settings or get_settings()

    if not await can_fetch(url, cfg):
        return FetchResult(
            status_code=None,
            body=b"",
            content_type=None,
            etag=None,
            last_modified=None,
            unchanged=False,
            error="robots.txt disallows fetch",
        )

    headers = conditional_headers(prior_artifact)
    try:
        async with build_http_client(cfg) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return FetchResult(
            status_code=None,
            body=b"",
            content_type=None,
            etag=None,
            last_modified=None,
            unchanged=False,
            error=str(exc),
        )

    if response.status_code == 304:
        return FetchResult(
            status_code=304,
            body=b"",
            content_type=None,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            unchanged=True,
        )

    if response.status_code >= 400:
        return FetchResult(
            status_code=response.status_code,
            body=b"",
            content_type=response.headers.get("content-type"),
            etag=None,
            last_modified=None,
            unchanged=False,
            error=f"HTTP {response.status_code}",
        )

    body = response.content
    if len(body) > cfg.crawl_max_bytes:
        return FetchResult(
            status_code=response.status_code,
            body=b"",
            content_type=response.headers.get("content-type"),
            etag=None,
            last_modified=None,
            unchanged=False,
            error=f"response exceeds max bytes ({cfg.crawl_max_bytes})",
        )

    content_type = response.headers.get("content-type")
    if content_type and ";" in content_type:
        content_type = content_type.split(";", 1)[0].strip()

    return FetchResult(
        status_code=response.status_code,
        body=body,
        content_type=content_type,
        etag=response.headers.get("etag"),
        last_modified=response.headers.get("last-modified"),
        unchanged=False,
    )
