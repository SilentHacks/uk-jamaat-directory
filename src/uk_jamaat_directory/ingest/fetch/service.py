from __future__ import annotations

from urllib.parse import urljoin

import httpx

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.fetch.client import build_http_client
from uk_jamaat_directory.ingest.fetch.conditional import conditional_headers
from uk_jamaat_directory.ingest.fetch.limits import read_limited_body
from uk_jamaat_directory.ingest.fetch.robots import can_fetch
from uk_jamaat_directory.ingest.fetch.security import ensure_resolvable_public_host
from uk_jamaat_directory.ingest.fetch.throttle import wait_for_domain
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import SourceArtifact

_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


def _normalize_content_type(content_type: str | None) -> str | None:
    if content_type and ";" in content_type:
        return content_type.split(";", 1)[0].strip()
    return content_type


async def fetch_url(
    url: str,
    *,
    prior_artifact: SourceArtifact | None = None,
    settings: Settings | None = None,
) -> FetchResult:
    cfg = settings or get_settings()
    current_url = url
    conditional = conditional_headers(prior_artifact)

    try:
        async with build_http_client(cfg) as client:
            for redirect_count in range(_MAX_REDIRECTS + 1):
                blocked = await ensure_resolvable_public_host(current_url)
                if blocked:
                    return FetchResult(
                        status_code=None,
                        body=b"",
                        content_type=None,
                        etag=None,
                        last_modified=None,
                        unchanged=False,
                        error=blocked,
                    )

                if not await can_fetch(current_url, cfg):
                    return FetchResult(
                        status_code=None,
                        body=b"",
                        content_type=None,
                        etag=None,
                        last_modified=None,
                        unchanged=False,
                        error="robots.txt disallows fetch",
                    )

                await wait_for_domain(current_url, cfg)

                request_headers = conditional if redirect_count == 0 else {}
                async with client.stream("GET", current_url, headers=request_headers) as response:
                    if response.status_code in _REDIRECT_STATUS:
                        if redirect_count >= _MAX_REDIRECTS:
                            return FetchResult(
                                status_code=response.status_code,
                                body=b"",
                                content_type=None,
                                etag=None,
                                last_modified=None,
                                unchanged=False,
                                error="too many redirects",
                            )
                        location = response.headers.get("location")
                        if not location:
                            return FetchResult(
                                status_code=response.status_code,
                                body=b"",
                                content_type=None,
                                etag=None,
                                last_modified=None,
                                unchanged=False,
                                error="redirect without location",
                            )
                        current_url = urljoin(current_url, location)
                        continue

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
                            content_type=_normalize_content_type(
                                response.headers.get("content-type")
                            ),
                            etag=None,
                            last_modified=None,
                            unchanged=False,
                            error=f"HTTP {response.status_code}",
                        )

                    body, size_error = await read_limited_body(response, cfg.crawl_max_bytes)
                    if size_error:
                        return FetchResult(
                            status_code=response.status_code,
                            body=b"",
                            content_type=_normalize_content_type(
                                response.headers.get("content-type")
                            ),
                            etag=None,
                            last_modified=None,
                            unchanged=False,
                            error=size_error,
                        )

                    return FetchResult(
                        status_code=response.status_code,
                        body=body or b"",
                        content_type=_normalize_content_type(response.headers.get("content-type")),
                        etag=response.headers.get("etag"),
                        last_modified=response.headers.get("last-modified"),
                        unchanged=False,
                    )
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

    return FetchResult(
        status_code=None,
        body=b"",
        content_type=None,
        etag=None,
        last_modified=None,
        unchanged=False,
        error="too many redirects",
    )
