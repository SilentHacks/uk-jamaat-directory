"""Local cache for live page verification fetches.

The verification gate fetches candidate pages over HTTP. This cache stores
``url -> (title, body_text)`` so that a dry-run followed by a live-run (or
any re-run within the TTL) does not re-fetch the same pages.

The cache is keyed by **URL only** (not mosque), because the page content is
independent of which mosque is being verified. The caller re-computes the
name ratio and postcode match from the cached text for each mosque.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_DEFAULT_CACHE_FILE = Path("data/cache/verification_pages.json")
_DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


class VerificationPageCache:
    """Disk-backed cache for fetched verification pages.

    Keys are normalised URLs. Values are ``{"timestamp": int, "title": str,
    "text": str}``.
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
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, url: str) -> tuple[str, str] | None:
        """Return (title, body_text) if present and not expired."""
        key = _normalise_url(url)
        entry = self._data.get(key)
        if entry is None:
            return None
        timestamp = entry.get("timestamp", 0)
        if time.time() - timestamp > self._ttl:
            del self._data[key]
            self._dirty = True
            return None
        return entry.get("title", ""), entry.get("text", "")

    def set(self, url: str, title: str, text: str) -> None:
        """Store a fetched page (marks dirty; does not write)."""
        key = _normalise_url(url)
        self._data[key] = {
            "timestamp": int(time.time()),
            "title": title,
            "text": text,
        }
        self._dirty = True

    def set_many(self, items: dict[str, tuple[str, str]]) -> None:
        """Store many pages at once (marks dirty)."""
        now = int(time.time())
        for url, (title, text) in items.items():
            key = _normalise_url(url)
            self._data[key] = {
                "timestamp": now,
                "title": title,
                "text": text,
            }
        self._dirty = True

    def commit(self) -> None:
        """Flush in-memory changes to disk if dirty."""
        if self._dirty:
            self._save()
            self._dirty = False

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


def _normalise_url(url: str) -> str:
    return url.strip().rstrip("/").lower()
