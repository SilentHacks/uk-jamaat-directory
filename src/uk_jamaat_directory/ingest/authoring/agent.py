"""Agent subprocess wrapper for the authoring orchestrator.

The orchestrator delegates authoring to a coding-agent CLI as a one-shot
subprocess. Which CLI (OpenCode, Claude Code, …) and how it is invoked is
decided by the :mod:`backends` module; this wrapper owns the shared
mechanics:

- runs the agent in the repo root so it can write directly to
  ``ingest/extract/repo_extractors/scripts/`` and ``data/authoring_results/``,
- captures stdout/stderr for diagnostics,
- reads the structured JSON result file the agent is instructed to write
  after finishing, so the orchestrator does not need to parse the agent's
  free-form text output.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.authoring.authoring_result import (
    AgentReport,
    AgentResult,
    read_authoring_result,
)
from uk_jamaat_directory.ingest.authoring.backends import AgentBackend, get_agent_backend


async def run_authoring_agent(
    *,
    prompt: str,
    settings: Settings,
    result_path: Path,
    cwd: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
    backend: AgentBackend | None = None,
) -> AgentResult:
    """Run the selected agent once and return the result read from the JSON file.

    The agent is instructed (via the prompt) to write a JSON file to
    *result_path* after finishing. The wrapper reads that file and
    populates :class:`AgentResult` with the structured data. If the file
    is missing or invalid, the task is marked ``failed``.

    The prompt is passed as a single positional/flag argument; it is a few
    KB and on Linux the ARG_MAX limit is in the megabytes. The agent is
    given network access; the prompt instructs it to stay on the source's
    registrable domain.
    """

    backend = backend or get_agent_backend(settings)
    bin_path = backend.resolve_binary()
    model = backend.resolve_model(settings)
    timeout = timeout_seconds or settings.authoring_per_source_timeout_seconds
    workdir = cwd or os.getcwd()

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    backend.apply_env(env, settings)

    command_repr = backend.describe(model=model, prompt=prompt)

    start = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        *backend.build_argv(bin_path=bin_path, model=model, prompt=prompt),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=workdir,
        env=env,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        msg = f"{backend.name} agent timed out after {timeout:.0f}s"
        raise TimeoutError(msg) from exc

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    excerpt = (stderr or stdout).strip()[:2000]

    result, read_error = read_authoring_result(result_path)
    if result is None:
        reason = read_error or "agent did not write the JSON result file"
        if process.returncode:
            reason = f"{reason} (agent exited rc={process.returncode})"
        return AgentResult(
            text="",
            duration_ms=duration_ms,
            command=command_repr,
            returncode=process.returncode or 0,
            stdout_excerpt=excerpt,
            report=AgentReport(status="failed", reason=reason),
        )

    return AgentResult(
        text="",
        duration_ms=duration_ms,
        command=command_repr,
        returncode=process.returncode or 0,
        stdout_excerpt=excerpt,
        report=AgentReport(
            status=result.status,
            target_url=result.target_url,
            target_kind=result.parsed_target_kind,
            script_path=result.script_path,
            reason=result.reason,
        ),
    )
