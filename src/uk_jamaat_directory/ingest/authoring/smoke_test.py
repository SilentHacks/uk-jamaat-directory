"""Execution smoke test for an authored extractor script.

Static AST checks prove a script is safe; this proves it *works*: fetch the
script's declared targets once (DB-free, no artifact persistence), run the
extractor in the sandbox, and validate the output structurally and
semantically. Used as the deploy gate by the orchestrator, as the agent's
self-test command, and by ``prune-repo-extractors``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorArtifact,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    load_all_extractors,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.runner import (
    build_sandbox_payload,
    run_sandbox,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.semantics import (
    check_result_semantics,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_extractor,
    check_extractor_result,
)
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.ingest.normalize import normalize_domain


@dataclass
class SmokeReport:
    ok: bool
    issues: list[str] = field(default_factory=list)
    rows: int = 0
    warnings: list[str] = field(default_factory=list)
    no_schedule_reason: str | None = None
    duration_ms: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "issues": self.issues,
            "rows": self.rows,
            "warnings": self.warnings,
            "no_schedule_reason": self.no_schedule_reason,
            "duration_ms": self.duration_ms,
        }


async def smoke_test_extractor(
    *,
    extractor_key: str,
    source_url: str,
    mosque_name: str = "",
    settings: Settings | None = None,
) -> SmokeReport:
    cfg = settings or get_settings()
    entries = [e for e in load_all_extractors(reload=True) if e.extractor.key == extractor_key]
    if not entries:
        return SmokeReport(ok=False, issues=[f"extractor not found: {extractor_key}"])
    extractor = entries[0].extractor

    domain = normalize_domain(source_url)
    issues = list(check_extractor(extractor, allowed_domain=domain))
    if issues:
        return SmokeReport(ok=False, issues=issues)

    artifacts: dict[str, ExtractorArtifact] = {}
    for target in extractor.targets:
        if target.requires_pdf or target.requires_ocr:
            artifacts[target.label] = ExtractorArtifact(
                target_label=target.label,
                target_url=target.url,
                content_type=None,
                body=b"",
                content_hash=None,
            )
        elif target.requires_javascript:
            from uk_jamaat_directory.ingest.fetch.playwright import fetch_rendered_html

            fetch = await fetch_rendered_html(
                target.url, settings=cfg, timeout_seconds=cfg.crawl_timeout_seconds
            )
        else:
            fetch = await fetch_url(target.url, settings=cfg)
        if not target.requires_pdf and not target.requires_ocr:
            if fetch.error or not fetch.ok:
                return SmokeReport(
                    ok=False,
                    issues=[
                        f"target {target.label} fetch failed: "
                        f"{fetch.error or f'http {fetch.status_code}'}"
                    ],
                )
            artifacts[target.label] = ExtractorArtifact(
                target_label=target.label,
                target_url=target.url,
                content_type=fetch.content_type,
                body=fetch.body or b"",
                content_hash=None,
            )

    payload = build_sandbox_payload(
        extractor_key=extractor.key,
        source_id="00000000-0000-0000-0000-000000000000",
        mosque_name=mosque_name,
        mosque_id=None,
        source_url=source_url,
        timezone="Europe/London",
        artifacts=artifacts,
    )
    heavy = any(
        t.requires_pdf or t.requires_ocr or t.requires_javascript for t in extractor.targets
    )
    sandbox = await run_sandbox(extractor.key, payload, settings=cfg, heavy=heavy)
    if not sandbox.ok or sandbox.result is None:
        return SmokeReport(
            ok=False,
            issues=[sandbox.error or "sandbox failed"],
            duration_ms=sandbox.duration_ms,
        )

    result = sandbox.result
    issues = list(check_extractor_result(result))
    issues.extend(check_result_semantics(result))
    return SmokeReport(
        ok=not issues,
        issues=issues,
        rows=len(result.rows),
        warnings=[w.message for w in result.warnings],
        no_schedule_reason=result.no_schedule_reason,
        duration_ms=sandbox.duration_ms,
    )
