from __future__ import annotations


class MosqueNotFoundError(LookupError):
    """Raised when an admin operation targets a mosque that does not exist."""


class DuplicateAliasError(ValueError):
    """Raised when an alias already exists for the mosque."""


class SourceNotFoundError(LookupError):
    """Raised when an admin operation targets a source that does not exist."""
