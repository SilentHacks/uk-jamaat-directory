"""Post-authoring validation for a draft extractor script.

Runs the static checks that ``validate-repo-extractor`` would run, and
returns the issues for the orchestrator to record. The agent already
validated the script in its own subprocess before reporting
``STATUS=authored``; the orchestrator re-runs the static check on the
file the agent reported so the task carries the precise issue list.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_extractor,
    check_script_source,
    validate_refresh_policy,
    validate_source_match,
)


@dataclass
class ValidationReport:
    issues: list[str]
    extractor: Any | None = None
    extractor_key: str | None = None
    extractor_version: str | None = None


def validate_draft_source(source: str) -> list[str]:
    """Run the static source checks against a draft script body."""

    result = check_script_source(source)
    return list(result.issues)


def validate_extractor_for_domain(
    *, extractor: BaseMosqueWebsiteExtractor, allowed_domain: str | None
) -> list[str]:
    issues: list[str] = list(validate_source_match(extractor.source_match))
    issues.extend(validate_refresh_policy(extractor.refresh_policy))
    issues.extend(check_extractor(extractor, allowed_domain=allowed_domain))
    return [issue for issue in issues if issue]


def write_draft_to_scripts(
    *,
    extractor_key: str,
    source: str,
    scripts_dir: str,
) -> str:
    """Write ``source`` to ``<scripts_dir>/<extractor_key>.py`` and return the path."""

    safe_key = re.sub(r"[^a-z0-9_]+", "_", extractor_key.lower()).strip("_")
    if not safe_key:
        msg = f"invalid extractor key: {extractor_key!r}"
        raise ValueError(msg)
    os.makedirs(scripts_dir, exist_ok=True)
    path = os.path.join(scripts_dir, f"{safe_key}.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    return path
