"""Overnight extractor authoring orchestrator.

The orchestrator hands each ``mosque_website`` source to the OpenCode CLI
as a subprocess and lets the agent navigate the source's registrable
domain to find the prayer-timetable page. The agent then either writes a
repo extractor script directly into
``ingest/extract/repo_extractors/scripts/`` or marks the source for
human review (PDF / image / OCR / JS-rendered targets).

Flow per source (concurrent, semaphore-bounded):

1. ``preflight_source`` confirms the source URL is reachable and records
   the predicted target kind. The agent is still free to disagree.
2. The orchestrator builds a prompt with the source URL, the registrable
   domain restriction, the canonical script path, the contract, and the
   structured ``STATUS=…`` summary the agent must emit.
3. The agent navigates the site, decides the target kind, and either
   writes the script or skips to the review queue.
4. On ``STATUS=authored`` the orchestrator reads the file the agent
   reported, runs the same static + capability gates as
   ``validate-repo-extractor``, then calls ``sync_repo_extractors`` to
   create the assignment.
5. On ``STATUS=skipped_review`` the orchestrator records the reason and
   target kind. No LLM call happens for unsupported kinds.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import (
    AuthoringTargetKind,
    AuthoringTaskStatus,
    SourceType,
)
from uk_jamaat_directory.ingest.authoring.agent import (
    AgentResult,
    is_opencode_available,
    run_authoring_agent,
)
from uk_jamaat_directory.ingest.authoring.authoring_prompt import (
    build_authoring_prompt,
)
from uk_jamaat_directory.ingest.authoring.discovery import (
    preflight_source,
)
from uk_jamaat_directory.ingest.authoring.validator_post import (
    validate_draft_source,
    write_draft_to_scripts,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.sync import (
    sync_repo_extractors,
)
from uk_jamaat_directory.ingest.normalize import normalize_domain
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    MosqueSource,
    SourceExtractorAssignment,
)

SCRIPTS_PACKAGE = "uk_jamaat_directory.ingest.extract.repo_extractors.scripts"
SCRIPTS_DIR = (
    "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts"
)


@dataclass
class OrchestrationSummary:
    candidates: int = 0
    preflight_ok: int = 0
    authored: int = 0
    deployed: int = 0
    skipped_review: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates": self.candidates,
            "preflight_ok": self.preflight_ok,
            "authored": self.authored,
            "deployed": self.deployed,
            "skipped_review": self.skipped_review,
            "failed": self.failed,
            "errors": list(self.errors),
        }


def _safe_extractor_key(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")


def _scripts_filesystem_path() -> str:
    """Resolve the on-disk path of the scripts package for the running
    process. The agent writes to this directory; the validator and the
    registry import from the same one.
    """

    try:
        spec = importlib.util.find_spec(SCRIPTS_PACKAGE)
    except (ModuleNotFoundError, ValueError):
        spec = None
    if spec is not None and spec.origin:
        return os.path.dirname(spec.origin)
    candidates = [
        os.path.abspath(
            os.path.join(
                os.getcwd(),
                "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts",
            )
        ),
        os.path.abspath(SCRIPTS_DIR),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    return candidates[0]


def _repo_root() -> str:
    """The repo root that contains the ``src/`` layout the agent should
    operate in. Defaults to the current working directory.
    """

    cwd = os.getcwd()
    src = os.path.join(cwd, "src")
    if os.path.isdir(src):
        return cwd
    parent = os.path.dirname(cwd)
    if os.path.isdir(os.path.join(parent, "src")):
        return parent
    return cwd


async def _list_candidate_sources(
    session: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[MosqueSource]:
    stmt = (
        select(MosqueSource)
        .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
        .where(MosqueSource.source_url.is_not(None))
    )
    if source_id is not None:
        stmt = stmt.where(MosqueSource.id == source_id)
    if limit is not None and source_id is None:
        stmt = stmt.limit(limit)
    sources = (await session.execute(stmt)).scalars().all()
    eligible: list[MosqueSource] = []
    for source in sources:
        metadata = source.metadata_ or {}
        if metadata.get("crawl_enabled") is False:
            continue
        assignment = await session.get(SourceExtractorAssignment, source.id)
        if assignment is not None and assignment.status == "active":
            continue
        eligible.append(source)
    return eligible


async def _existing_task(
    session: AsyncSession, source_id: uuid.UUID
) -> ExtractorAuthoringTask | None:
    return (
        await session.execute(
            select(ExtractorAuthoringTask).where(
                ExtractorAuthoringTask.source_id == source_id
            )
        )
    ).scalar_one_or_none()


async def _mosque_name(session: AsyncSession, source: MosqueSource) -> str:
    if source.mosque_id is None:
        return source.display_name or "Unknown mosque"
    mosque = await session.get(Mosque, source.mosque_id)
    if mosque is None:
        return source.display_name or "Unknown mosque"
    return mosque.name


def _task_should_skip(task: ExtractorAuthoringTask | None) -> bool:
    if task is None:
        return False
    return task.status in {
        AuthoringTaskStatus.DEPLOYED.value,
        AuthoringTaskStatus.AWAITING_REVIEW.value,
    }


@dataclass
class _SourceProcessResult:
    status: str
    error: str | None = None
    discovered_url: str | None = None
    target_kind: str = AuthoringTargetKind.UNKNOWN.value
    extractor_key: str | None = None
    extractor_version: str | None = None
    script_path: str | None = None
    validation_issues: list[str] = field(default_factory=list)
    agent_model: str | None = None
    agent_command: str | None = None
    agent_duration_ms: int | None = None
    agent_stdout_excerpt: str | None = None


def _read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _resolve_script_absolute_path(script_path: str) -> str | None:
    """Turn the agent's reported ``SCRIPT_PATH`` (which may be repo-relative
    or absolute) into an absolute path the orchestrator can read.
    """

    if not script_path:
        return None
    if os.path.isabs(script_path):
        return script_path
    candidates = [
        os.path.abspath(os.path.join(_repo_root(), script_path)),
        os.path.abspath(script_path),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0]


def _classify_agent_result(
    *,
    agent_result: AgentResult,
    source: MosqueSource,
    extractor_key: str,
    scripts_dir: str,
) -> _SourceProcessResult:
    """Translate the agent's structured report into a ``_SourceProcessResult``."""

    report = agent_result.report
    extractor_version = datetime.now(UTC).strftime("%Y.%m.%d.1")
    base = _SourceProcessResult(
        status=AuthoringTaskStatus.FAILED.value,
        discovered_url=report.target_url or source.source_url,
        target_kind=(
            report.target_kind.value
            if report.target_kind is not None
            else AuthoringTargetKind.UNKNOWN.value
        ),
        extractor_key=extractor_key,
        extractor_version=extractor_version,
        agent_model=None,
        agent_command=agent_result.command,
        agent_duration_ms=agent_result.duration_ms,
        agent_stdout_excerpt=agent_result.stdout_excerpt,
    )

    if not report.status:
        base.error = "agent did not emit a STATUS=… summary"
        return base
    status = report.status.lower().strip()

    if status == "skipped_review":
        base.status = AuthoringTaskStatus.SKIPPED_REVIEW.value
        base.error = report.reason or "skipped by agent (no reason given)"
        return base

    if status == "failed":
        base.status = AuthoringTaskStatus.FAILED.value
        base.error = report.reason or "agent reported failure (no reason given)"
        return base

    if status != "authored":
        base.error = f"agent reported unknown status: {status!r}"
        return base

    if not report.script_path:
        base.error = "agent reported authored but no SCRIPT_PATH"
        return base
    absolute = _resolve_script_absolute_path(report.script_path)
    if absolute is None or not os.path.isfile(absolute):
        base.error = f"script not found at {report.script_path}"
        return base

    source_text = _read_text_file(absolute)
    if source_text is None:
        base.error = f"could not read script at {absolute}"
        return base

    issues = validate_draft_source(source_text)
    if issues:
        base.validation_issues = issues
        base.script_path = absolute
        base.error = "; ".join(issues)
        return base

    # The agent may have written anywhere on disk. Normalise the file into
    # the canonical scripts directory under the orchestrator's chosen key.
    target_path = os.path.join(scripts_dir, f"{extractor_key}.py")
    if os.path.abspath(absolute) != os.path.abspath(target_path):
        written = write_draft_to_scripts(
            extractor_key=extractor_key,
            source=source_text,
            scripts_dir=scripts_dir,
        )
        base.script_path = written
    else:
        base.script_path = absolute
    base.status = AuthoringTaskStatus.AWAITING_REVIEW.value
    return base


async def _run_post_sync(
    session: AsyncSession, *, source_id: uuid.UUID
) -> tuple[str, str | None]:
    """Run :func:`sync_repo_extractors` for one source and return the
    post-sync state.
    """

    sync_result = await sync_repo_extractors(session, source_id=source_id)
    await session.flush()
    assignment = await session.get(SourceExtractorAssignment, source_id)
    if assignment is None:
        invalid = "; ".join(
            item.get("issues", ["invalid"])
            for item in sync_result.invalid
            if item.get("source_id") == str(source_id)
        )
        return (
            AuthoringTaskStatus.FAILED.value,
            invalid or "no assignment created",
        )
    return (
        AuthoringTaskStatus.DEPLOYED.value,
        None,
    )


async def _process_one(
    *,
    session: AsyncSession,
    source: MosqueSource,
    semaphore: asyncio.Semaphore,
    summary: OrchestrationSummary,
    dry_run: bool,
    settings: Settings,
) -> None:
    async with semaphore:
        started = time.monotonic()
        result: _SourceProcessResult | None = None
        try:
            result = await asyncio.wait_for(
                _process_source(
                    session=session, source=source, settings=settings
                ),
                timeout=settings.authoring_per_source_timeout_seconds,
            )
        except TimeoutError:
            result = _SourceProcessResult(
                status=AuthoringTaskStatus.FAILED.value,
                error=(
                    "orchestrator timeout after "
                    f"{settings.authoring_per_source_timeout_seconds:.0f}s"
                ),
            )

        task = await _existing_task(session, source.id)
        if task is None:
            task = ExtractorAuthoringTask(
                id=uuid.uuid4(),
                source_id=source.id,
            )
            session.add(task)
        task.status = result.status
        task.discovered_url = result.discovered_url
        task.target_kind = result.target_kind
        task.extractor_key = result.extractor_key
        task.extractor_version = result.extractor_version
        task.script_path = result.script_path
        task.validation_issues = [
            {"issue": issue} for issue in result.validation_issues
        ]
        task.agent_model = result.agent_model
        task.agent_command = result.agent_command
        task.agent_duration_ms = result.agent_duration_ms
        task.agent_stdout_excerpt = result.agent_stdout_excerpt
        task.error = result.error
        task.started_at = datetime.now(UTC)
        task.finished_at = datetime.now(UTC)
        task.metadata_ = {
            "duration_ms": int((time.monotonic() - started) * 1000),
            "source_url": source.source_url,
        }

        if (
            not dry_run
            and result.status == AuthoringTaskStatus.AWAITING_REVIEW.value
        ):
            post_status, post_error = await _run_post_sync(
                session, source_id=source.id
            )
            task.status = post_status
            if post_error:
                task.error = post_error

        await session.flush()

        if task.status == AuthoringTaskStatus.DEPLOYED.value:
            summary.deployed += 1
        elif task.status == AuthoringTaskStatus.AWAITING_REVIEW.value:
            summary.authored += 1
        elif task.status == AuthoringTaskStatus.SKIPPED_REVIEW.value:
            summary.skipped_review += 1
        else:
            summary.failed += 1
        if result.error:
            summary.errors.append(f"{source.id}: {result.error[:200]}")


async def _process_source(
    *,
    session: AsyncSession,
    source: MosqueSource,
    settings: Settings,
) -> _SourceProcessResult:
    mosque_name = await _mosque_name(session, source)
    extractor_key = (
        _safe_extractor_key(f"{mosque_name.replace(' ', '_')}_{str(source.id)[:8]}")
        or f"source_{str(source.id)[:8]}"
    )
    extractor_version = datetime.now(UTC).strftime("%Y.%m.%d.1")

    preflight = await preflight_source(
        source_url=source.source_url or "", settings=settings
    )
    if not preflight.reachable:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=preflight.error or "preflight: source unreachable",
            target_kind=preflight.predicted_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    if not is_opencode_available():
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error="opencode binary not found on PATH",
            discovered_url=source.source_url,
            target_kind=preflight.predicted_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    domain = preflight.domain or normalize_domain(source.source_url) or ""
    scripts_dir = _scripts_filesystem_path()
    script_path = os.path.join(scripts_dir, f"{extractor_key}.py")
    prompt = build_authoring_prompt(
        source_id=str(source.id),
        mosque_name=mosque_name,
        website_url=source.source_url or "",
        extractor_key=extractor_key,
        script_path=os.path.relpath(script_path, _repo_root()),
        domain=domain,
        predicted_kind=preflight.predicted_kind,
        max_pages=8,
    )

    try:
        agent_result: AgentResult = await run_authoring_agent(
            prompt=prompt,
            settings=settings,
            cwd=_repo_root(),
        )
    except TimeoutError as exc:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=str(exc),
            discovered_url=source.source_url,
            target_kind=preflight.predicted_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    result = _classify_agent_result(
        agent_result=agent_result,
        source=source,
        extractor_key=extractor_key,
        scripts_dir=scripts_dir,
    )
    result.agent_model = settings.ai_agent_model
    return result


async def run_overnight_orchestrator(
    *,
    session: AsyncSession,
    settings: Settings | None = None,
    source_id: uuid.UUID | None = None,
    limit: int | None = None,
    concurrency: int | None = None,
    dry_run: bool = False,
    on_progress: Callable[[OrchestrationSummary], Awaitable[None]] | None = None,
) -> OrchestrationSummary:
    cfg = settings or get_settings()
    workers = max(1, concurrency or cfg.authoring_concurrency)
    semaphore = asyncio.Semaphore(workers)
    summary = OrchestrationSummary()

    sources = await _list_candidate_sources(
        session, source_id=source_id, limit=limit
    )
    summary.candidates = len(sources)
    if on_progress is not None:
        await on_progress(summary)
    if not sources:
        return summary

    tasks = [
        asyncio.create_task(
            _process_one(
                session=session,
                source=source,
                semaphore=semaphore,
                summary=summary,
                dry_run=dry_run,
                settings=cfg,
            )
        )
        for source in sources
    ]
    await asyncio.gather(*tasks)
    if on_progress is not None:
        await on_progress(summary)
    return summary
