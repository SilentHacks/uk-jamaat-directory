"""Authoring result JSON file contract and helpers.

The agent writes a JSON file to a deterministic path after it finishes. The
orchestrator reads the file (and validates it with Pydantic) to know what the
agent did — no parsing of the agent's free-form text output is required.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from uk_jamaat_directory.domain import AuthoringTargetKind

# The directory that stores agent result JSON files (one per source).
# Ignored by git; part of the repo's operational-data directory.
RESULTS_DIR = Path("data/authoring_results")

# Schema version for forward compatibility.
RESULT_SCHEMA_VERSION = "1.0"

# Allowed statuses the agent may report.
VALID_STATUSES: frozenset[str] = frozenset({"authored", "skipped_review", "failed"})


class OpenCodeNotInstalledError(RuntimeError):
    """Raised when the ``opencode`` binary is not on ``PATH``."""


@dataclass
class AgentReport:
    """Structured report parsed from the agent's JSON result file."""

    status: str | None = None
    target_url: str | None = None
    target_kind: AuthoringTargetKind | None = None
    script_path: str | None = None
    reason: str | None = None


@dataclass
class AgentResult:
    """Result of running the agent subprocess once."""

    text: str
    duration_ms: int
    command: str
    returncode: int
    stdout_excerpt: str
    report: AgentReport = field(default_factory=AgentReport)


def is_opencode_available() -> bool:
    return shutil.which("opencode") is not None


def _resolve_opencode_bin() -> str:
    path = shutil.which("opencode")
    if not path:
        msg = (
            "opencode binary 'opencode' not found on PATH. "
            "Install OpenCode or set the opencode executable on PATH."
        )
        raise OpenCodeNotInstalledError(msg)
    return path


class AuthoringResultJson(BaseModel):
    """Schema for the JSON file the agent writes after finishing.

    The file is the single source of truth for the agent's outcome. The
    orchestrator reads it, validates it, and decides whether to deploy the
    script, queue the source for review, or mark the task as failed.
    """

    status: str = Field(..., description="authored | skipped_review | failed")
    target_url: str = Field(
        ..., description="The timetable URL the agent found (or the source URL)"
    )
    target_kind: str = Field(..., description="html | pdf | image | rendered_html | json | unknown")
    script_path: str | None = Field(
        default=None,
        description="Repo-relative path to the authored script (authored only)",
    )
    reason: str | None = Field(
        default=None,
        description="Short reason (skipped_review or failed only)",
    )
    version: str = Field(default=RESULT_SCHEMA_VERSION, description="Schema version")

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v

    @field_validator("target_kind")
    @classmethod
    def _validate_target_kind(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {k.value for k in AuthoringTargetKind}:
            raise ValueError(f"target_kind must be one of {AuthoringTargetKind}")
        return v

    @property
    def parsed_target_kind(self) -> AuthoringTargetKind:
        try:
            return AuthoringTargetKind(self.target_kind)
        except ValueError:
            return AuthoringTargetKind.UNKNOWN


def authoring_result_path(source_id: uuid.UUID) -> Path:
    """Return the deterministic path for a source's result JSON file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR / f"{source_id}.json"


def read_authoring_result(
    path: Path,
) -> tuple[AuthoringResultJson | None, str | None]:
    """Read and validate the JSON file at *path*.

    Returns ``(result, None)`` on success, or ``(None, reason)`` describing
    exactly why the file could not be used (missing / unreadable / invalid
    JSON / schema violation) so failures stay debuggable.
    """
    if not path.is_file():
        return None, "agent did not write the JSON result file"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"result file unreadable: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"result file is not valid JSON: {exc}"
    try:
        return AuthoringResultJson.model_validate(data), None
    except Exception as exc:  # noqa: BLE001
        return None, f"result file failed schema validation: {exc}"


def clean_authoring_result(path: Path) -> None:
    """Remove the JSON file at *path* if it exists.

    Called before starting the agent to prevent stale results from a previous
    run being read.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def write_authoring_result(
    path: Path,
    *,
    status: str,
    target_url: str,
    target_kind: str,
    script_path: str | None = None,
    reason: str | None = None,
    version: str = RESULT_SCHEMA_VERSION,
) -> None:
    """Write a validated result JSON file.

    Used by the agent prompt (via the ``write`` tool) to emit the final
    report. This is a convenience for the agent so it does not have to
    hand-craft JSON.
    """
    result = AuthoringResultJson(
        status=status,
        target_url=target_url,
        target_kind=target_kind,
        script_path=script_path,
        reason=reason,
        version=version,
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
