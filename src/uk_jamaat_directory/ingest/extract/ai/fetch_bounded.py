from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.artifacts import latest_artifact_for_source
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import MosqueSource

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    stripped = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", stripped).strip()


# Common paths to probe when looking for prayer timetables.
_TIMETABLE_PATHS = (
    "/prayer-times",
    "/timetable",
    "/salah",
    "/prayer",
    "/times",
    "/prayers",
)


@dataclass(frozen=True)
class BoundedPageResult:
    url: str
    body_snippet: str
    content_type: str
    status_code: int


async def fetch_bounded_pages(
    session: AsyncSession,
    source: MosqueSource,
    settings: Settings,
) -> list[BoundedPageResult]:
    """Fetch a bounded set of pages for a mosque website source.

    Fetches the homepage first, then up to ``settings.ai_profiling_max_pages - 1``
    common timetable paths relative to the domain.  Only successful ``text/html``
    responses are returned.

    Args:
        session: Database session (used to look up prior artifacts for conditional GET).
        source: The ``MOSQUE_WEBSITE`` source with ``source_url`` set.
        settings: Project settings.

    Returns:
        List of ``BoundedPageResult`` objects, each truncated to
        ``settings.ai_profiling_max_chars_per_page`` characters.
    """
    max_pages = settings.ai_profiling_max_pages
    max_chars = settings.ai_profiling_max_chars_per_page
    homepage = source.source_url
    if not homepage:
        return []

    pages: list[BoundedPageResult] = []
    urls_to_fetch = [homepage]

    # Build relative probe URLs, keeping only those under the same origin.
    for path in _TIMETABLE_PATHS:
        candidate = urljoin(homepage, path)
        if candidate != homepage and candidate not in urls_to_fetch:
            urls_to_fetch.append(candidate)
        if len(urls_to_fetch) >= max_pages:
            break

    for url in urls_to_fetch:
        if len(pages) >= max_pages:
            break

        prior = await latest_artifact_for_source(session, source.id)
        fetch: FetchResult = await fetch_url(
            url,
            prior_artifact=prior,
            settings=settings,
        )

        if fetch.error:
            continue
        if fetch.status_code != 200:
            continue
        ct = (fetch.content_type or "").lower()
        if "html" not in ct:
            continue

        raw = fetch.body.decode("utf-8", errors="replace")
        text = _strip_html_tags(raw)[:max_chars]
        pages.append(
            BoundedPageResult(
                url=url,
                body_snippet=text,
                content_type=fetch.content_type or "text/html",
                status_code=fetch.status_code,
            )
        )

    return pages
