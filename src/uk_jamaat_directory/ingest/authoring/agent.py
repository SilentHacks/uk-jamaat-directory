"""OpenCode CLI agent wrapper.

The orchestrator delegates authoring to the OpenCode CLI as a subprocess. We
keep the integration thin: build the prompt, run ``opencode -m <model> run
--format json <prompt>``, parse the JSON-line stream, and return the joined
``text`` parts plus timing. There is no tool-calling protocol and no shared
state between calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

from uk_jamaat_directory.config import Settings

OPENCODE_BIN = "opencode"

_FENCE_PATTERN_ANY = "```"
_FENCE_LANG_PATTERN_PREFIX = "```python"
_FENCE_LANG_PATTERN_ALT = "```py"


class OpenCodeNotInstalledError(RuntimeError):
    """Raised when the ``opencode`` binary is not on ``PATH``."""


@dataclass
class AgentResult:
    text: str
    duration_ms: int
    command: str
    returncode: int
    stdout_excerpt: str


def _resolve_opencode_bin() -> str:
    path = shutil.which(OPENCODE_BIN)
    if not path:
        msg = (
            f"opencode binary '{OPENCODE_BIN}' not found on PATH. "
            "Install OpenCode or set the opencode executable on PATH."
        )
        raise OpenCodeNotInstalledError(msg)
    return path


def _build_argv(*, model: str, prompt: str) -> list[str]:
    return [
        OPENCODE_BIN,
        "-m",
        model,
        "run",
        "--format",
        "json",
        prompt,
    ]


def extract_python_block(text: str) -> str | None:
    """Pull the first ``python`` fenced block out of an OpenCode response."""
    fence = text.find(_FENCE_LANG_PATTERN_PREFIX)
    if fence < 0:
        fence = text.find(_FENCE_LANG_PATTERN_ALT)
    if fence < 0:
        return None
    start = text.find("\n", fence) + 1
    end = text.find(_FENCE_PATTERN_ANY, start)
    if end < 0:
        return text[start:].strip()
    return text[start:end].strip()


def _parse_json_stream(stdout: str) -> tuple[str, int]:
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
    return "".join(parts), len(parts)


async def run_authoring_agent(
    *,
    prompt: str,
    settings: Settings,
    cwd: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> AgentResult:
    """Run OpenCode once and return the joined text output.

    Raises ``asyncio.TimeoutError`` if the subprocess exceeds
    ``timeout_seconds`` (defaults to ``authoring_per_source_timeout_seconds``).
    """

    bin_path = _resolve_opencode_bin()
    model = settings.ai_agent_model
    argv = _build_argv(model=model, prompt=prompt)
    command_repr = " ".join(argv[:5]) + f" …({len(prompt)} chars)"
    timeout = timeout_seconds or settings.authoring_per_source_timeout_seconds

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    if settings.ai_agent_api_key:
        env.setdefault("OPENAI_API_KEY", settings.ai_agent_api_key)
    if settings.ai_agent_base_url:
        env.setdefault("OPENAI_BASE_URL", settings.ai_agent_base_url)

    start = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        bin_path,
        *argv[1:],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
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
    text, _parts = _parse_json_stream(stdout)
    excerpt = (stderr or stdout).strip()[:2000]
    return AgentResult(
        text=text or stdout,
        duration_ms=duration_ms,
        command=command_repr,
        returncode=process.returncode or 0,
        stdout_excerpt=excerpt,
    )


def is_opencode_available() -> bool:
    return shutil.which(OPENCODE_BIN) is not None
