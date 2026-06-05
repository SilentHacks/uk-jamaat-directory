from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from uk_jamaat_directory.schemas.public import (
    ChangeEventPublic,
    MosqueDetailPublic,
    PublicScheduleOccurrence,
)


@dataclass
class SourceCountSummary:
    public_sources: int = 0
    excluded_restricted_sources: int = 0
    total_linked_sources: int = 0


@dataclass
class ExportDataset:
    version: str
    schema_version: str
    published_at: datetime | None
    mosques: list[MosqueDetailPublic] = field(default_factory=list)
    occurrences: list[PublicScheduleOccurrence] = field(default_factory=list)
    changes: list[ChangeEventPublic] = field(default_factory=list)
    attribution: list[str] = field(default_factory=list)
    source_counts: SourceCountSummary = field(default_factory=SourceCountSummary)


@dataclass
class ExportFileInfo:
    name: str
    object_key: str
    url: str
    content_type: str
    body: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.body)


@dataclass
class ExportResult:
    version: str
    files_written: int = 0
    mosque_count: int = 0
    occurrence_count: int = 0
    change_count: int = 0
    checksum: str | None = None
    errors: list[str] = field(default_factory=list)
