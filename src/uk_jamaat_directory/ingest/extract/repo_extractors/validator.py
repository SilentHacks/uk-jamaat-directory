from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from uk_jamaat_directory.ingest.extract.helpers.capabilities import (
    ocr_available,
    pdf_text_available,
    render_html_available,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    CONTRACT_ID,
    TARGET_KINDS,
    BaseMosqueWebsiteExtractor,
    ExtractorResult,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
)

BANNED_IMPORTS: frozenset[str] = frozenset(
    {
        "subprocess",
        "socket",
        "ssl",
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "urllib3",
        "http",
        "http.client",
        "asyncio",
        "asyncio.subprocess",
        "multiprocessing",
        "os",
        "shutil",
        "pathlib",
        "glob",
        "tempfile",
        "ctypes",
        "ctypes.util",
        "importlib",
        "pickle",
        "marshal",
        "code",
        "codeop",
        "compile",
        "ast",
        "builtins",
        "open",
    }
)

ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "uk_jamaat_directory.domain",
        "uk_jamaat_directory.ingest.extract.repo_extractors.contract",
        "uk_jamaat_directory.ingest.extract.repo_extractors.declarative",
        "uk_jamaat_directory.ingest.extract.helpers",
    }
)

ALLOWED_STDLIB: frozenset[str] = frozenset(
    {
        "__future__",
        "datetime",
        "zoneinfo",
        "re",
        "math",
        "decimal",
        "collections",
        "dataclasses",
        "typing",
        "abc",
        "enum",
        "copy",
        "itertools",
        "functools",
        "json",
        "hashlib",
    }
)


@dataclass(frozen=True)
class StaticCheckResult:
    ok: bool
    issues: tuple[str, ...]


def _resolve_module_name(module: str | None) -> str:
    if module is None:
        return ""
    return module.split(".")[0]


def check_script_source(source: str) -> StaticCheckResult:
    issues: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return StaticCheckResult(ok=False, issues=(f"syntax error: {exc}",))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _resolve_module_name(alias.name)
                if root in BANNED_IMPORTS or root in {"os", "pathlib", "subprocess"}:
                    issues.append(f"banned import: {alias.name}")
                    continue
                if root not in ALLOWED_STDLIB and not any(
                    alias.name.startswith(prefix) for prefix in ALLOWED_MODULES
                ):
                    issues.append(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = _resolve_module_name(module)
            if root in BANNED_IMPORTS:
                issues.append(f"banned import from: {module}")
                continue
            if root not in ALLOWED_STDLIB and not any(
                module.startswith(prefix) for prefix in ALLOWED_MODULES
            ):
                issues.append(f"import not allowed: {module}")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            issues.append(f"banned construct: {type(node).__name__}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"eval", "exec", "compile"}:
                issues.append(f"banned call: {func.id}")

    return StaticCheckResult(ok=not issues, issues=tuple(issues))


_HOST_PATTERN = re.compile(r"^[a-z0-9.\-]+$")


def check_target_url(url: str, *, allowed_domain: str | None) -> str | None:
    from uk_jamaat_directory.ingest.domain_policy import (
        is_aggregator_url,
        is_trusted_widget_url,
        is_umbrella_url,
    )

    if not url:
        return "target url is empty"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return f"unsupported target url scheme: {parsed.scheme}"
    host = (parsed.hostname or "").lower()
    if not host:
        return "target url missing host"
    # Aggregators are rejected even when they are the source's own domain:
    # they publish calculated prayer-start times, not jamaat times.
    if is_aggregator_url(url):
        return f"target url {host} is a directory/aggregator site"
    if is_umbrella_url(url):
        return f"target url {host} is a multi-mosque umbrella site (needs review)"
    if is_trusted_widget_url(url):
        return None
    if allowed_domain is None:
        return "no allowed domain for source"
    allowed = allowed_domain.lower()
    if not (host == allowed or host.endswith(f".{allowed}")):
        return f"target url {host} is outside allowed domain {allowed}"
    return None


def check_capabilities(
    extractor: BaseMosqueWebsiteExtractor,
    *,
    strict_ocr: bool = False,
) -> tuple[str, ...]:
    issues: list[str] = []
    for target in extractor.targets:
        kind_value = target.kind.value if hasattr(target.kind, "value") else str(target.kind)
        if kind_value not in TARGET_KINDS:
            issues.append(f"unknown target kind: {kind_value}")
        if target.requires_pdf and not pdf_text_available():
            issues.append("target requires pdf but pymupdf is not installed")
        if target.requires_ocr and not ocr_available() and strict_ocr:
            issues.append("target requires ocr but pytesseract is not installed")
        if target.requires_javascript and not render_html_available():
            issues.append("target requires rendered html but playwright is not installed")
    return tuple(issues)


def check_extractor(
    extractor: BaseMosqueWebsiteExtractor,
    *,
    allowed_domain: str | None,
) -> tuple[str, ...]:
    issues: list[str] = []
    if not extractor.targets:
        issues.append("extractor declares no targets")
    seen: set[str] = set()
    for target in extractor.targets:
        if target.label in seen:
            issues.append(f"duplicate target label: {target.label}")
        seen.add(target.label)
        url_issue = check_target_url(target.url, allowed_domain=allowed_domain)
        if url_issue is not None:
            issues.append(url_issue)
    issues.extend(check_capabilities(extractor, strict_ocr=False))
    return tuple(issues)


def check_extractor_result(result: ExtractorResult) -> tuple[str, ...]:
    issues: list[str] = []
    if not result.rows and not result.no_schedule_reason:
        issues.append("rows=[] requires no_schedule_reason")
    seen: set[tuple[Any, ...]] = set()
    for row in result.rows:
        key = (row.date, row.prayer.value, row.session_number)
        if key in seen:
            issues.append(f"duplicate row for {key}")
        seen.add(key)
        if row.evidence.contract != CONTRACT_ID:
            issues.append(f"row evidence missing {CONTRACT_ID} contract")
        if not row.evidence.gate_passed:
            issues.append("row evidence marked gate_passed=false")
    return tuple(issues)


def validate_source_match(match: SourceMatch) -> tuple[str, ...]:
    issues: list[str] = []
    for domain in match.domains:
        if not _HOST_PATTERN.match(domain.lower()):
            issues.append(f"invalid source_match domain: {domain}")
    return tuple(issues)


def validate_refresh_policy(policy: RefreshPolicy) -> tuple[str, ...]:
    issues: list[str] = []
    if policy.frequency not in RunFrequency:
        issues.append(f"unsupported refresh frequency: {policy.frequency}")
    return tuple(issues)
