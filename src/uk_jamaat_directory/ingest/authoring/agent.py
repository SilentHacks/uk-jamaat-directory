"""OpenCode CLI agent wrapper for the authoring orchestrator.

The orchestrator delegates authoring to the OpenCode CLI as a subprocess
(``opencode -m <model> run --format json <prompt>``). The wrapper:

- runs OpenCode in the repo root so the agent can write directly to
  ``ingest/extract/repo_extractors/scripts/`` and ``data/authoring_results/``,
- captures the JSON-event stream for diagnostics,
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
    _resolve_opencode_bin,
    read_authoring_result,
)


async def run_authoring_agent(
    *,
    prompt: str,
    settings: Settings,
    result_path: Path,
    cwd: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> AgentResult:
    """Run OpenCode once and return the result read from the JSON file.

    The agent is instructed (via the prompt) to write a JSON file to
    *result_path* after finishing. The wrapper reads that file and
    populates :class:`AgentResult` with the structured data. If the file
    is missing or invalid, the task is marked ``failed``.

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

    command_repr = f"opencode -m {model} run --format json <prompt:{len(prompt)} chars>"

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
        stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        msg = f"opencode agent timed out after {timeout:.0f}s"
        raise TimeoutError(msg) from exc

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    excerpt = (stderr or stdout).strip()[:2000]

    result = read_authoring_result(result_path)
    if result is None:
        return AgentResult(
            text="",
            duration_ms=duration_ms,
            command=command_repr,
            returncode=process.returncode or 0,
            stdout_excerpt=excerpt,
            report=AgentReport(
                status="failed",
                reason="agent did not write the JSON result file",
            ),
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
