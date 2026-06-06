"""Tier 2: search-engine website discovery provider (exa.ai).

For each mosque missing a ``website_url``, construct a quoted query
``"{name}" {postcode}`` and call the Exa Search API. Results are filtered
through the deny-list; up to three candidates per mosque are proposed as
:class:`WebsiteLead` objects.

Search-engine leads are **not** in ``PUBLIC_LINKED_PROVIDERS``, so the
verification gate will fetch each page live and require a name + postcode
match before promotion.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.ingest.discovery.websites.search.cache import (
    SearchCache,
)
from uk_jamaat_directory.ingest.discovery.websites.search.exa_client import (
    ExaClient,
    ExaResult,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteLeadResult,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.discovery.websites.verify import domain_is_denied
from uk_jamaat_directory.models.core import Mosque

_SEARCH_PROVIDER = "exa"
_NUM_RESULTS = 3


async def propose_search_engine_leads(
    session: AsyncSession,
    *,
    exa_client: ExaClient | None = None,
    cache: SearchCache | None = None,
    delay_seconds: float = 1.0,
) -> tuple[list[WebsiteLead], WebsiteLeadResult]:
    """Propose website leads for mosques without a website via Exa search.

    Parameters
    ----------
    session
        Database session.
    exa_client
        Exa API client. Required unless every query is cached.
    cache
        Optional :class:`SearchCache` to avoid repeated API calls.
    delay_seconds
        Sleep between API requests to respect rate limits.
    """
    result = WebsiteLeadResult()
    leads: list[WebsiteLead] = []

    mosques = await _load_target_mosques(session)
    if not mosques:
        return leads, result

    client = exa_client
    cache_obj = cache or SearchCache()

    for mosque in mosques:
        query = _build_query(mosque)
        if not query:
            continue

        search_results: list[ExaResult] = []
        cached = cache_obj.get(_SEARCH_PROVIDER, query)
        if cached is not None:
            search_results = cached
        elif client is not None:
            try:
                search_results = await client.search(query, num_results=_NUM_RESULTS)
                cache_obj.set(_SEARCH_PROVIDER, query, search_results)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"exa search failed for {query}: {exc}")
                continue
            # rate-limiting delay between live API calls
            await asyncio.sleep(delay_seconds)
        else:
            # no cache hit and no client — skip
            continue

        for rank, item in enumerate(search_results, start=1):
            if domain_is_denied(item.url):
                continue
            leads.append(
                WebsiteLead(
                    mosque_id=mosque.id,
                    url=item.url,
                    provider=WebsiteProvider.SEARCH_ENGINE,
                    reason=f"exa_search_rank_{rank}",
                    matched_postcode=mosque.postcode,
                    extra={
                        "query": query,
                        "result_title": item.title,
                        "result_rank": str(rank),
                    },
                )
            )
            result.candidates_proposed += 1

    return leads, result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_target_mosques(session: AsyncSession) -> list[Mosque]:
    stmt = select(Mosque).where(
        (Mosque.website_url.is_(None)) | (Mosque.website_url == ""),
        Mosque.postcode.is_not(None),
    )
    return list((await session.execute(stmt)).scalars().all())


def _build_query(mosque: Mosque) -> str | None:
    """Build a quoted-name + postcode query for Exa."""
    name = (mosque.name or "").strip()
    postcode = (mosque.postcode or "").strip()
    if not name or not postcode:
        return None
    return f'"{name}" {postcode}'
