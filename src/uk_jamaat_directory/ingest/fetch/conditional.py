from __future__ import annotations

from uk_jamaat_directory.models.core import SourceArtifact


def conditional_headers(prior_artifact: SourceArtifact | None) -> dict[str, str]:
    if prior_artifact is None:
        return {}
    headers: dict[str, str] = {}
    if prior_artifact.etag:
        headers["If-None-Match"] = prior_artifact.etag
    if prior_artifact.last_modified:
        headers["If-Modified-Since"] = prior_artifact.last_modified
    return headers
