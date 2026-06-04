from __future__ import annotations

import pytest

from uk_jamaat_directory.domain import SourcePublicationPolicy
from uk_jamaat_directory.ingest.policy import can_publish_to_public_api, parse_publication_policy


def test_parse_publication_policy() -> None:
    assert (
        parse_publication_policy("public_redistribution_allowed")
        == SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED
    )


def test_parse_publication_policy_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="invalid publication policy"):
        parse_publication_policy("maybe_public")


def test_can_publish_only_when_allowed() -> None:
    assert can_publish_to_public_api(SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED)
    assert not can_publish_to_public_api(SourcePublicationPolicy.UNKNOWN)
    assert not can_publish_to_public_api(SourcePublicationPolicy.PRIVATE_USE_ONLY)
