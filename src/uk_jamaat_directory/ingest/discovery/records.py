from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from uk_jamaat_directory.domain import Confidence, SourcePublicationPolicy, SourceType


class MatchDecision(StrEnum):
    AUTO_LINK = "auto_link"
    CREATE_NEEDS_REVIEW = "create_needs_review"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


@dataclass
class DiscoveryRecord:
    source_type: SourceType
    external_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: str = "GB"
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source_url: str | None = None
    attribution: str | None = None
    publication_policy: SourcePublicationPolicy = SourcePublicationPolicy.UNKNOWN
    confidence: Confidence = Confidence.COMMUNITY
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.name


@dataclass
class ScoredMosqueCandidate:
    mosque_id: uuid.UUID
    score: float
    reasons: list[str]


@dataclass
class DiscoveryMatch:
    decision: MatchDecision
    mosque_id: uuid.UUID | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    alternatives: list[ScoredMosqueCandidate] = field(default_factory=list)


@dataclass
class DiscoveryImportResult:
    sources_linked: int = 0
    sources_created: int = 0
    mosques_created: int = 0
    mosques_linked: int = 0
    reviews_created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
