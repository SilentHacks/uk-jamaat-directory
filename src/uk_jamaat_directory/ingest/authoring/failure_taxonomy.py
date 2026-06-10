"""Classify authoring failures so resume can tell permanent from retryable.

Permanent categories (``PERMANENT_FAILURE_CATEGORIES`` in ``domain``) are
skipped on subsequent runs; retryable categories are re-attempted until the
task's ``attempts`` reaches ``authoring_max_attempts``.
"""

from __future__ import annotations

import re

from uk_jamaat_directory.domain import AuthoringFailureCategory

_DEAD_SITE_PATTERNS = (
    "cannot resolve host",
    "name or service not known",
    "getaddrinfo",
    "http 404",
    "http 410",
    "http 401",
    "http 403",
    "certificate_verify_failed",
    "ssl",
    "blocked host address",
    "source url has no scheme or host",
)

_TRANSIENT_PATTERNS = (
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "timed out",
    "timeout",
    "connection reset",
    "connection refused",
    "temporarily",
)

_HTTP_5XX = re.compile(r"http 5\d\d")


def classify_failure(
    *,
    preflight_error: str | None = None,
    agent_reason: str | None = None,
    validation_issues: list[str] | None = None,
    agent_timed_out: bool = False,
) -> AuthoringFailureCategory:
    if agent_timed_out:
        return AuthoringFailureCategory.TIMEOUT

    if preflight_error:
        lowered = preflight_error.lower()
        if "robots" in lowered:
            return AuthoringFailureCategory.BLOCKED_ROBOTS
        if _HTTP_5XX.search(lowered) or any(p in lowered for p in _TRANSIENT_PATTERNS):
            return AuthoringFailureCategory.TRANSIENT_NETWORK
        if any(p in lowered for p in _DEAD_SITE_PATTERNS):
            return AuthoringFailureCategory.DEAD_SITE
        return AuthoringFailureCategory.TRANSIENT_NETWORK

    if agent_reason:
        lowered = agent_reason.lower()
        if "aggregator" in lowered or "directory listing" in lowered:
            return AuthoringFailureCategory.AGGREGATOR
        if "no jamaat" in lowered or "no prayer timetable" in lowered:
            return AuthoringFailureCategory.PERMANENT_NO_JAMAAT
        if "did not write the json result" in lowered or "agent" in lowered:
            return AuthoringFailureCategory.AGENT_ERROR

    if validation_issues:
        return AuthoringFailureCategory.VALIDATION_FAILED

    return AuthoringFailureCategory.AGENT_ERROR
