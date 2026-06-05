from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FetchResult:
    status_code: int | None
    body: bytes
    content_type: str | None
    etag: str | None
    last_modified: str | None
    unchanged: bool
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.unchanged or self.status_code == 200)
