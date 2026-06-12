from __future__ import annotations

import asyncio
import json
import subprocess
import time
import uuid

import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.authoring.agent import run_authoring_agent
from uk_jamaat_directory.ingest.authoring.authoring_result import (
    AuthoringResultJson,
    authoring_result_path,
    clean_authoring_result,
    read_authoring_result,
    write_authoring_result,
)
from uk_jamaat_directory.ingest.authoring.backends import AgentBackend


class _SpawnTreeBackend(AgentBackend):
    """Backend that launches a bash process spawning a marked child."""

    name = "spawn_tree"
    binary = "bash"
    default_model = "test"

    def __init__(self, marker: str) -> None:
        self._marker = marker

    def build_argv(self, *, bin_path, model, prompt, agent_name=None):
        # A child sleep carrying the marker, plus a foreground sleep so the
        # parent stays alive long enough to hit the timeout.
        return [bin_path, "-c", f"sleep 300 # {self._marker}\nsleep 300"]


async def test_run_authoring_agent_timeout_kills_process_tree(tmp_path) -> None:
    marker = f"agent-timeout-{uuid.uuid4().hex}"
    backend = _SpawnTreeBackend(marker)
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        await run_authoring_agent(
            prompt="unused",
            settings=Settings(_env_file=None),
            result_path=tmp_path / "result.json",
            backend=backend,
            timeout_seconds=0.5,
        )
    # Returned promptly, not after the 300s sleep.
    assert time.monotonic() - started < 30
    # Give the SIGKILL a moment to propagate, then confirm no orphan child.
    await asyncio.sleep(0.5)
    leftover = subprocess.run(
        ["pgrep", "-f", marker], capture_output=True, text=True
    ).stdout.split()
    assert not leftover, f"agent subprocess tree was orphaned: {leftover}"


def test_authoring_result_path_is_deterministic() -> None:
    source_id = uuid.UUID("4e6c1114-33ce-4d61-9fe0-754403251eb6")
    path = authoring_result_path(source_id)
    assert path.name == "4e6c1114-33ce-4d61-9fe0-754403251eb6.json"
    assert "data/authoring_results" in str(path)


def test_clean_authoring_result_removes_file(tmp_path) -> None:
    path = tmp_path / "test.json"
    path.write_text("{}", encoding="utf-8")
    assert path.exists()
    clean_authoring_result(path)
    assert not path.exists()


def test_clean_authoring_result_is_noop_when_missing(tmp_path) -> None:
    path = tmp_path / "missing.json"
    clean_authoring_result(path)
    assert not path.exists()


def test_read_authoring_result_valid_json(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "status": "authored",
                "target_url": "https://example.com/prayer-times",
                "target_kind": "html",
                "script_path": "src/.../example.py",
                "reason": None,
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    result, error = read_authoring_result(path)
    assert result is not None
    assert error is None
    assert result.status == "authored"
    assert result.target_url == "https://example.com/prayer-times"
    assert result.target_kind == "html"
    assert result.script_path == "src/.../example.py"
    assert result.reason is None
    assert result.version == "1.0"
    assert result.parsed_target_kind == AuthoringTargetKind.HTML


def test_read_authoring_result_missing_file(tmp_path) -> None:
    path = tmp_path / "missing.json"
    result, error = read_authoring_result(path)
    assert result is None
    assert "did not write" in error


def test_read_authoring_result_invalid_json(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text("not json", encoding="utf-8")
    result, error = read_authoring_result(path)
    assert result is None
    assert "not valid JSON" in error


def test_read_authoring_result_bad_status(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "status": "unknown_status",
                "target_url": "https://example.com",
                "target_kind": "html",
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    result, error = read_authoring_result(path)
    assert result is None
    assert "schema validation" in error


def test_read_authoring_result_bad_kind(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "status": "authored",
                "target_url": "https://example.com",
                "target_kind": "mystery",
                "version": "1.0",
            }
        ),
        encoding="utf-8",
    )
    result, error = read_authoring_result(path)
    assert result is None
    assert "schema validation" in error


def test_write_authoring_result_roundtrip(tmp_path) -> None:
    path = tmp_path / "result.json"
    write_authoring_result(
        path,
        status="skipped_review",
        target_url="https://pdf.test/timetable.pdf",
        target_kind="pdf",
        reason="pdf target — ocr not yet implemented",
    )
    result, error = read_authoring_result(path)
    assert result is not None
    assert error is None
    assert result.status == "skipped_review"
    assert result.target_kind == "pdf"
    assert result.reason == "pdf target — ocr not yet implemented"


def test_authoring_result_json_parsed_target_kind() -> None:
    result = AuthoringResultJson(
        status="authored",
        target_url="https://example.com",
        target_kind="rendered_html",
        version="1.0",
    )
    assert result.parsed_target_kind == AuthoringTargetKind.RENDERED_HTML


def test_authoring_result_json_parsed_target_kind_unknown() -> None:
    result = AuthoringResultJson(
        status="authored",
        target_url="https://example.com",
        target_kind="html",
        version="1.0",
    )
    assert result.parsed_target_kind == AuthoringTargetKind.HTML


def test_authoring_result_json_validates_status() -> None:
    with pytest.raises(ValueError, match="status"):
        AuthoringResultJson(
            status="foo",
            target_url="https://example.com",
            target_kind="html",
        )


def test_authoring_result_json_validates_target_kind() -> None:
    with pytest.raises(ValueError, match="target_kind"):
        AuthoringResultJson(
            status="authored",
            target_url="https://example.com",
            target_kind="mystery",
        )


def test_authoring_result_json_status_case_insensitive() -> None:
    result = AuthoringResultJson(
        status="AUTHORED",
        target_url="https://example.com",
        target_kind="html",
    )
    assert result.status == "authored"


def test_authoring_result_json_target_kind_case_insensitive() -> None:
    result = AuthoringResultJson(
        status="authored",
        target_url="https://example.com",
        target_kind="HTML",
    )
    assert result.target_kind == "html"
