"""Tier 2: search-engine website discovery provider (exa.ai).

For each mosque missing a ``website_url``, construct a quoted query
``"{name}" {postcode}`` and call the Exa Search API. Results are filtered
through the deny-list; up to three candidates per mosque are proposed as
:class:`WebsiteLead` objects.

Search-engine leads are **not** in ``PUBLIC_LINKED_PROVIDERS``, so the
verification gate will fetch each page live and require a name + postcode
match before promotion.

Optimisations
-------------
* **Parallelism:** up to ``max_concurrency`` searches run concurrently,
  respecting Exa's ~10 QPS rate limit.
* **Deduplication:** identical (name, postcode) queries are grouped and
  searched once, with leads cloned to every matching mosque.
* **Batch caching:** all API results are written to disk in a single
  :meth:`SearchCache.commit` at the end.
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
    max_concurrency: int = 8,
    limit: int | None = None,
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
    max_concurrency
        Concurrent Exa requests (default 8, safely under the 10 QPS limit).
    limit
        If given, only search the first *limit* mosques (ordered by UUID for
        determinism). Useful for trial runs.
    """
    result = WebsiteLeadResult()
    leads: list[WebsiteLead] = []

    mosques = await _load_target_mosques(session, limit=limit)
    if not mosques:
        return leads, result

    # 1. Build query -> [mosques] map so identical queries are deduplicated.
    query_map: dict[str, list[Mosque]] = {}
    for mosque in mosques:
        query = _build_query(mosque)
        if not query:
            continue
        query_map.setdefault(query, []).append(mosque)

    if not query_map:
        return leads, result

    cache_obj = cache or SearchCache()

    # 2. Check cache for all queries first (synchronous, fast).
    uncached_queries: list[str] = []
    all_results: dict[str, list[ExaResult]] = {}
    for query in query_map:
        cached = cache_obj.get(_SEARCH_PROVIDER, query)
        if cached is not None:
            all_results[query] = cached
        else:
            uncached_queries.append(query)

    # 3. Fire parallel API calls for everything that was not cached.
    if uncached_queries and exa_client is not None:
        api_results = await _search_many(
            exa_client, uncached_queries, num_results=_NUM_RESULTS
        )
        # Persist successes to the in-memory cache (flushed later).
        cache_obj.set_many(_SEARCH_PROVIDER, api_results)
        all_results.update(api_results)
        # Log failures
        failed = set(uncached_queries) - set(api_results)
        for query in failed:
            result.errors.append(f"exa search failed for {query}")

    # 4. Build leads from cached + API results.
    for query, mosques_for_query in query_map.items():
        search_results = all_results.get(query, [])
        for mosque in mosques_for_query:
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

    # 5. Flush cache once.
    cache_obj.commit()
    return leads, result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_target_mosques(
    session: AsyncSession,
    limit: int | None = None,
) -> list[Mosque]:
    stmt = (
        select(Mosque)
        .where(
            (Mosque.website_url.is_(None)) | (Mosque.website_url == ""),
            Mosque.postcode.is_not(None),
        )
        .order_by(Mosque.id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await session.execute(stmt)).scalars().all())


def _build_query(mosque: Mosque) -> str | None:
    """Build a quoted-name + postcode query for Exa."""
    name = (mosque.name or "").strip()
    postcode = (mosque.postcode or "").strip()
    if not name or not postcode:
        return None
    return f'"{name}" {postcode}'


async def _search_many(
    client: ExaClient,
    queries: list[str],
    *,
    num_results: int = 3,
) -> dict[str, list[ExaResult]]:
    """Run many Exa searches in parallel and return only successes.

    The client's semaphore controls concurrency; ``asyncio.gather``
    coordinates the parallel execution.
    """
    tasks = [client.search(q, num_results=num_results) for q in queries]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, list[ExaResult]] = {}
    for query, res in zip(queries, raw, strict=True):
        if isinstance(res, Exception):
            continue
        out[query] = res
    return out
