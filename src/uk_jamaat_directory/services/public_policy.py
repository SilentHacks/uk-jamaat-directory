from __future__ import annotations

from sqlalchemy import ColumnElement

from uk_jamaat_directory.domain import SourcePublicationPolicy
from uk_jamaat_directory.models.core import MosqueSource

PUBLIC_PUBLICATION_POLICY = SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED


def is_public_source_policy(policy: SourcePublicationPolicy | str) -> bool:
    value = policy.value if isinstance(policy, SourcePublicationPolicy) else policy
    return value == PUBLIC_PUBLICATION_POLICY.value


def public_source_filter() -> ColumnElement[bool]:
    return MosqueSource.publication_policy == PUBLIC_PUBLICATION_POLICY
