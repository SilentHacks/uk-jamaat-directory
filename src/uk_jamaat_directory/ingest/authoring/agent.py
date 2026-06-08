"""OpenCode CLI agent wrapper for the authoring orchestrator.

The orchestrator delegates authoring to the OpenCode CLI as a subprocess
(``opencode -m <model> run --format json <prompt>``). The wrapper:

- runs OpenCode in the repo root so the agent can write directly to
  ``ingest/extract/repo_extractors/scripts/``,
- parses the JSON-event stream and accumulates the agent's text,
- looks for a structured ``STATUS=…`` summary in the last 1 KB of stdout
  so the orchestrator can decide what to do next,
- exposes the joined text and a parsed :class:`AgentReport` on
  :class:`AgentResult`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import AuthoringTargetKind

OPENCODE_BIN = "opencode"

# Pattern: lines of the form ``KEY=value`` describing the outcome. The
# agent emits these at the very end of its reply.
_SUMMARY_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]+)\s*=\s*(.+?)\s*$")
_SUMMARY_TAIL_BYTES = 1024

_SUMMARY_KEYS: frozenset[str] = frozenset(
    {"STATUS", "TARGET_URL", "TARGET_KIND", "SCRIPT_PATH", "REASON"}
)


class OpenCodeNotInstalledError(RuntimeError):
    """Raised when the ``opencode`` binary is not on ``PATH``."""


@dataclass
class AgentReport:
    status: str | None = None
    target_url: str | None = None
    target_kind: AuthoringTargetKind | None = None
    script_path: str | None = None
    reason: str | None = None


@dataclass
class AgentResult:
    text: str
    duration_ms: int
    command: str
    returncode: int
    stdout_excerpt: str
    report: AgentReport = field(default_factory=AgentReport)


def _resolve_opencode_bin() -> str:
    path = shutil.which(OPENCODE_BIN)
    if not path:
        msg = (
            f"opencode binary '{OPENCODE_BIN}' not found on PATH. "
            "Install OpenCode or set the opencode executable on PATH."
        )
        raise OpenCodeNotInstalledError(msg)
    return path


def parse_agent_report(stdout_tail: str) -> AgentReport:
    """Parse the agent's structured summary from the tail of its stdout.

    The agent is expected to end its reply with a block of lines like::

        STATUS=authored
        TARGET_URL=https://example.com/prayer-times
        TARGET_KIND=html
        SCRIPT_PATH=src/uk_jamaat_directory/.../my_key.py

    The parser finds the LAST contiguous block of ``KEY=VALUE`` lines,
    blank lines, and code fences. Unknown keys are ignored. Lines of
    freeform prose break the block.
    """

    report = AgentReport()
    if not stdout_tail:
        return report

    lines = stdout_tail.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            if current:
                blocks.append(current)
                current = []
            continue
        if _SUMMARY_LINE_RE.match(stripped):
            current.append(stripped)
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    if not blocks:
        return report
    summary_lines = blocks[-1]

    for line in summary_lines:
        match = _SUMMARY_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key == "STATUS":
            report.status = value
        elif key == "TARGET_URL":
            report.target_url = value
        elif key == "TARGET_KIND":
            try:
                report.target_kind = AuthoringTargetKind(value)
            except ValueError:
                report.target_kind = AuthoringTargetKind.UNKNOWN
        elif key == "SCRIPT_PATH":
            report.script_path = value
        elif key == "REASON":
            report.reason = value
    return report


def _parse_json_stream(stdout: str) -> str:
    """Accumulate the joined ``text`` events from ``opencode --format json``."""
    parts: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("part") or {}
        if event.get("type") == "text" and payload.get("type") == "text":
            text = payload.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _tail(text: str, *, n_bytes: int) -> str:
    if not text:
        return ""
    if len(text) <= n_bytes:
        return text
    return text[-n_bytes:]


async def run_authoring_agent(
    *,
    prompt: str,
    settings: Settings,
    cwd: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> AgentResult:
    """Run OpenCode once and return the joined text + parsed summary.

    The OpenCode CLI requires a positional ``message`` (or a
    ``--command``); ``-f`` is an attachment, not a substitute. The
    orchestrator's prompt is short enough (a few KB) to pass as a single
    positional argument; on Linux the ARG_MAX limit is in the megabytes.
    The agent is given network access; the prompt instructs it to stay on
    the source's registrable domain.
    """

    bin_path = _resolve_opencode_bin()
    model = settings.ai_agent_model
    timeout = timeout_seconds or settings.authoring_per_source_timeout_seconds
    workdir = cwd or os.getcwd()

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    if settings.ai_agent_api_key:
        env.setdefault("OPENAI_API_KEY", settings.ai_agent_api_key)
    if settings.ai_agent_base_url:
        env.setdefault("OPENAI_BASE_URL", settings.ai_agent_base_url)

    command_repr = (
        f"opencode -m {model} run --format json <prompt:{len(prompt)} chars>"
    )

    start = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        bin_path,
        "-m",
        model,
        "run",
        "--format",
        "json",
        prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workdir,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        msg = f"opencode agent timed out after {timeout:.0f}s"
        raise TimeoutError(msg) from exc

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    text = _parse_json_stream(stdout)
    tail = _tail(stdout, n_bytes=_SUMMARY_TAIL_BYTES)
    report = parse_agent_report(tail)
    excerpt = (stderr or stdout).strip()[:2000]
    return AgentResult(
        text=text or stdout,
        duration_ms=duration_ms,
        command=command_repr,
        returncode=process.returncode or 0,
        stdout_excerpt=excerpt,
        report=report,
    )


def is_opencode_available() -> bool:
    return shutil.which(OPENCODE_BIN) is not None
