"""Post-authoring validation for a draft extractor script.

Runs the static, capability, and output-contract checks that
``validate-repo-extractor`` would run, and returns the issues for the
orchestrator to record. Also performs an optional dry-run against a synthetic
fixture so we can refuse to deploy scripts that crash inside the sandbox.
"""

from __future__ import annotations

import importlib
import importlib.resources
import re
import uuid
from dataclasses import dataclass
from typing import Any

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.runner import (
    SandboxRunResult,
    run_sandbox,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_extractor,
    check_extractor_result,
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


def _safe_load_module(module_name: str) -> Any | None:
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 — surface as validation issue
        return exc


def _read_module_source(module_name: str) -> str | None:
    parts = module_name.split(".")
    package_name = ".".join(parts[:-1])
    module_file = parts[-1] + ".py"
    try:
        return (
            importlib.resources.files(package_name).joinpath(module_file).read_text()
        )
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        return None


def _iter_safely(iterable: Any) -> list[str]:
    try:
        return [str(item) for item in iterable]
    except Exception as exc:  # noqa: BLE001
        return [f"load error: {exc!r}"]


def list_registered_module_names() -> list[str]:
    from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
        iter_script_modules,
    )

    return _iter_safely(iter_script_modules())


def validate_draft_source(source: str) -> list[str]:
    result = check_script_source(source)
    return list(result.issues)


def validate_extractor_for_domain(
    *, extractor: BaseMosqueWebsiteExtractor, allowed_domain: str | None
) -> list[str]:
    issues: list[str] = list(validate_source_match(extractor.source_match))
    issues.extend(validate_refresh_policy(extractor.refresh_policy))
    issues.extend(check_extractor(extractor, allowed_domain=allowed_domain))
    return [issue for issue in issues if issue]


async def dry_run_draft(
    *,
    extractor: BaseMosqueWebsiteExtractor,
    fixture: dict[str, Any] | None = None,
    settings: Settings,
) -> tuple[bool, list[str]]:
    """Run the draft through the sandbox with a synthetic payload.

    Returns ``(ok, issues)``. ``ok=False`` means the script raised or the
    output validator rejected the result.
    """

    fixture = fixture or {
        "timetable": "<!doctype html><html><body><table>"
        "<tr><th>Date</th><th>Prayer</th><th>Adhan</th><th>Jamaat</th></tr>"
        "<tr><td>2099-06-09</td><td>Fajr</td><td>03:30</td><td>04:00</td></tr>"
        "</table></body></html>"
    }
    artifacts = {
        target.label: {
            "target_label": target.label,
            "target_url": target.url,
            "content_type": "text/html",
            "body_hex": body.encode("utf-8").hex(),
            "content_hash": None,
        }
        for target, body in zip(
            extractor.targets,
            _body_per_target(extractor, fixture),
            strict=False,
        )
    }
    payload = {
        "extractor_key": extractor.key,
        "source_id": str(uuid.uuid4()),
        "mosque_name": "Dry Run Masjid",
        "mosque_id": None,
        "source_url": "https://synthetic.example/prayer-timetable",
        "timezone": "Europe/London",
        "artifacts": artifacts,
    }
    sandbox: SandboxRunResult = await run_sandbox(
        extractor.key,
        payload,
        settings=settings,
        heavy=any(
            t.requires_pdf or t.requires_ocr or t.requires_javascript
            for t in extractor.targets
        ),
    )
    issues: list[str] = []
    if not sandbox.ok or sandbox.result is None:
        issues.append(sandbox.error or "sandbox failed")
        return False, issues
    issues.extend(check_extractor_result(sandbox.result))
    if issues:
        return False, issues
    return True, []


def _body_per_target(extractor: Any, fixture: dict[str, str]) -> list[str]:
    bodies: list[str] = []
    for target in extractor.targets:
        body = fixture.get(target.label)
        if body is None:
            body = fixture.get("timetable", "<!doctype html><html><body></body></html>")
        bodies.append(body)
    return bodies


def write_draft_to_scripts(
    *,
    extractor_key: str,
    source: str,
    scripts_dir: str,
) -> str:
    """Write ``source`` to ``<scripts_dir>/<extractor_key>.py`` and return the path."""

    import os

    safe_key = re.sub(r"[^a-z0-9_]+", "_", extractor_key.lower()).strip("_")
    if not safe_key:
        msg = f"invalid extractor key: {extractor_key!r}"
        raise ValueError(msg)
    os.makedirs(scripts_dir, exist_ok=True)
    path = os.path.join(scripts_dir, f"{safe_key}.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    return path
