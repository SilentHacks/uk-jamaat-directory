"""Shared dataclasses and the provider protocol for website discovery."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from uk_jamaat_directory.models.core import Mosque


class WebsiteProvider(StrEnum):
    """Identifier for each lead source. Stable string for storage."""

    MIB_METADATA = "mib_metadata"
    OSM_TAG_RECHECK = "osm_tag_recheck"
    CHARITY_COMMISSION = "charity_commission"
    OSCR = "oscr"
    WIKIDATA = "wikidata"
    DUCKDUCKGO = "duckduckgo"


@dataclass(frozen=True)
class WebsiteLead:
    """A candidate website URL discovered for a single mosque.

    The ``provider`` is the signal source; the URL is what was found. The
    ``reason`` carries why this provider suggested it (e.g. "charity_number_match").
    The optional ``linked_source_id`` flags the lead as coming from a public,
    redistributable source row already linked to the mosque, which is a
    pass-through under the moderate strictness policy.
    """

    mosque_id: uuid.UUID
    url: str
    provider: WebsiteProvider
    reason: str
    matched_postcode: str | None = None
    linked_source_id: uuid.UUID | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class WebsiteLeadResult:
    candidates_proposed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates_proposed": self.candidates_proposed,
            "errors": list(self.errors),
        }


class WebsiteLeadProvider(Protocol):
    """A pluggable lead source."""

    name: WebsiteProvider

    async def propose_leads(self, mosque: Mosque) -> Iterable[WebsiteLead]: ...
