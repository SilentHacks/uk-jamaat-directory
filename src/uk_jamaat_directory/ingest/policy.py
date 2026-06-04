from __future__ import annotations

from uk_jamaat_directory.domain import SourcePublicationPolicy
from uk_jamaat_directory.services.public_policy import is_public_source_policy


def parse_publication_policy(value: str) -> SourcePublicationPolicy:
    try:
        return SourcePublicationPolicy(value.strip().lower())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in SourcePublicationPolicy)
        msg = f"invalid publication policy '{value}'; expected one of: {allowed}"
        raise ValueError(msg) from exc


def can_publish_to_public_api(policy: SourcePublicationPolicy) -> bool:
    return is_public_source_policy(policy)
