from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorResult,
)


@dataclass(frozen=True)
class SandboxRunResult:
    ok: bool
    result: ExtractorResult | None
    error: str | None
    duration_ms: int
    raw_output: dict[str, Any] | None = None


def _resolve_timeout_seconds(
    extractor_kind_needs_heavy: bool, settings: Settings
) -> float:
    if extractor_kind_needs_heavy:
        return float(getattr(settings, "repo_extractor_ocr_timeout_seconds", 120.0))
    return float(getattr(settings, "repo_extractor_timeout_seconds", 30.0))


async def run_sandbox(
    extractor_key: str,
    input_payload: dict[str, Any],
    *,
    settings: Settings,
    heavy: bool = False,
) -> SandboxRunResult:
    timeout = _resolve_timeout_seconds(heavy, settings)
    with tempfile.TemporaryDirectory(prefix="repo_extractor_") as tmp:
        input_path = os.path.join(tmp, "input.json")
        output_path = os.path.join(tmp, "output.json")
        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump(input_payload, handle)
        start = asyncio.get_event_loop().time()
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "uk_jamaat_directory.ingest.extract.repo_extractors.sandbox",
                "--input",
                input_path,
                "--output",
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C.UTF-8",
                },
            )
        except FileNotFoundError as exc:
            return SandboxRunResult(
                ok=False,
                result=None,
                error=f"failed to launch sandbox: {exc}",
                duration_ms=0,
            )

        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            return SandboxRunResult(
                ok=False,
                result=None,
                error=f"sandbox timed out after {timeout}s",
                duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
            )

        stderr = (await process.stderr.read()).decode("utf-8", errors="replace")
        if process.returncode != 0:
            return SandboxRunResult(
                ok=False,
                result=None,
                error=f"sandbox failed (rc={process.returncode}): {stderr.strip()[:2000]}",
                duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
            )

        try:
            with open(output_path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return SandboxRunResult(
                ok=False,
                result=None,
                error=f"sandbox output unreadable: {exc}",
                duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
            )

        try:
            result = ExtractorResult.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            return SandboxRunResult(
                ok=False,
                result=None,
                error=f"sandbox output invalid: {exc}",
                duration_ms=int((asyncio.get_event_loop().time() - start) * 1000),
                raw_output=raw,
            )
        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)
        return SandboxRunResult(
            ok=True, result=result, error=None, duration_ms=duration_ms, raw_output=raw
        )
