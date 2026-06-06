"""Thin async client for the Exa Search API.

The free tier gives 1,000 requests/month and 10 QPS. We keep the client
minimal: one method, plain-JSON requests, and explicit retry/backoff on
rate-limit (429) and transient server errors.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

_EXA_API_URL = "https://api.exa.ai/search"
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2.0


@dataclass(frozen=True)
class ExaResult:
    """One search result from Exa."""

    title: str
    url: str


class ExaClient:
    """Async Exa Search API client.

    Parameters
    ----------
    api_key:
        Exa API key (from dashboard.exa.ai).
    timeout:
        Per-request timeout in seconds.
    """

    def __init__(self, *, api_key: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, *, num_results: int = 3) -> list[ExaResult]:
        """Run an Exa search and return the top *num_results* items.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff on
        429/5xx. Non-retryable 4xx responses are raised as-is.
        """
        headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "query": query,
            "type": "auto",
            "numResults": num_results,
        }

        last_exception: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        _EXA_API_URL,
                        headers=headers,
                        json=payload,
                    )
                    if response.status_code == 429:
                        # rate limited — back off and retry
                        wait = _RETRY_BACKOFF_BASE**attempt
                        await asyncio.sleep(wait)
                        continue
                    if 500 <= response.status_code < 600:
                        # transient server error — back off and retry
                        wait = _RETRY_BACKOFF_BASE**attempt
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    data = response.json()
                    return _parse_results(data)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_exception = exc
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF_BASE**attempt
                    await asyncio.sleep(wait)
                continue

        raise ExaSearchError(
            f"Exa search failed after {_MAX_RETRIES} retries: {last_exception}"
        ) from last_exception


class ExaSearchError(Exception):
    """Raised when the Exa search call fails definitively."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_results(data: dict) -> list[ExaResult]:
    """Parse the Exa /search JSON body into :class:`ExaResult` items."""
    results: list[ExaResult] = []
    raw_results = data.get("results") or []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        url = item.get("url") or ""
        if url:
            results.append(ExaResult(title=str(title), url=str(url)))
    return results
