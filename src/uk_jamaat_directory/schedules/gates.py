from __future__ import annotations

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import ExtractionKind
from uk_jamaat_directory.ingest.policy import can_publish_to_public_api
from uk_jamaat_directory.models.core import MosqueSource


def can_publish_candidate(
    source: MosqueSource,
    *,
    extraction_kind: ExtractionKind | None,
    settings: Settings | None = None,
) -> tuple[bool, str | None]:
    """Return (allowed, reason) for publishing a candidate from this source."""
    if not can_publish_to_public_api(source.publication_policy):
        return False, "source publication policy does not allow public redistribution"

    if extraction_kind == ExtractionKind.AI:
        cfg = settings or get_settings()
        if not cfg.publish_allow_ai:
            return False, "AI extraction requires explicit publish_allow_ai override"

    return True, None
