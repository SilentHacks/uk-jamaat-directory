"""Local file cache for search-engine results.

Keeps a JSON file on disk so repeated discovery runs do not burn API quota
on identical queries. Entries expire after 30 days.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from uk_jamaat_directory.ingest.discovery.websites.search.exa_client import (
    ExaResult,
)

_DEFAULT_CACHE_FILE = Path("data/cache/search_results.json")
_DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


class SearchCache:
    """Disk-backed cache for search queries.

    Keys are ``"provider:query"`` strings. Values are lists of
    :class:`ExaResult` with a timestamp.
    """

    def __init__(
        self,
        *,
        cache_file: Path | None = None,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._path = cache_file or _DEFAULT_CACHE_FILE
        self._ttl = ttl_seconds
        self._data: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, provider: str, query: str) -> list[ExaResult] | None:
        """Return cached results if present and not expired."""
        key = _key(provider, query)
        entry = self._data.get(key)
        if entry is None:
            return None
        timestamp = entry.get("timestamp", 0)
        if time.time() - timestamp > self._ttl:
            # expired — purge and return None
            del self._data[key]
            self._save()
            return None
        results = entry.get("results", [])
        return [ExaResult(**item) for item in results]

    def set(self, provider: str, query: str, results: list[ExaResult]) -> None:
        """Store results for a query."""
        key = _key(provider, query)
        self._data[key] = {
            "timestamp": int(time.time()),
            "results": [asdict(r) for r in results],
        }
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            self._data = {}
            return
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _key(provider: str, query: str) -> str:
    return f"{provider}:{query}"
