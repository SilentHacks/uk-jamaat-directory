"""Overnight extractor authoring orchestrator.

This is the implementation behind the ``orchestrate-authoring`` CLI. Given a
list of ``mosque_website`` sources, it:

1. Picks candidates that do not yet have an active repo extractor
   (``source_extractor_assignments.status != 'active'`` or missing).
2. For each candidate, runs :mod:`discovery` to find a likely timetable URL
   and classify the target kind.
3. For HTML / rendered HTML targets, calls the OpenCode CLI to author a
   Python extractor script.
4. Validates the draft (static + capability + sandbox dry-run).
5. Writes the draft to ``ingest/extract/repo_extractors/scripts/`` and runs
   :func:`sync_repo_extractors` so the assignment is created in the DB.

PDF, image, and other unsupported kinds are marked ``skipped_review`` without
spawning an LLM.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
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
    extract_python_block,
    is_opencode_available,
    run_authoring_agent,
)
from uk_jamaat_directory.ingest.authoring.discovery import (
    DiscoveryResult,
    discover_timetable_url,
    looks_like_javascript_widget,
)
from uk_jamaat_directory.ingest.authoring.validator_post import (
    validate_draft_source,
    write_draft_to_scripts,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.authoring_prompt import (
    build_authoring_prompt,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.sync import (
    sync_repo_extractors,
)
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    MosqueSource,
    SourceExtractorAssignment,
)

SCRIPTS_PACKAGE = (
    "uk_jamaat_directory.ingest.extract.repo_extractors.scripts"
)
SCRIPTS_DIR = "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts"


@dataclass
class OrchestrationSummary:
    candidates: int = 0
    discovered: int = 0
    authored: int = 0
    deployed: int = 0
    skipped_review: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates": self.candidates,
            "discovered": self.discovered,
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
    """Resolve the on-disk path of the scripts package for the running process.

    The orchestrator writes the file using the same absolute path that
    ``importlib`` will use to load it. We add the repo source root to
    ``sys.path`` if necessary so the file can be imported by the sandbox
    immediately after writing.
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


async def _existing_assignment_statuses(
    session: AsyncSession, source_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, str]:
    rows = (
        await session.execute(
            select(SourceExtractorAssignment.source_id, SourceExtractorAssignment.status).where(
                SourceExtractorAssignment.source_id.in_(list(source_ids))
            )
        )
    ).all()
    return {row[0]: row[1] for row in rows}


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


async def _existing_tasks(
    session: AsyncSession, source_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, ExtractorAuthoringTask]:
    rows = (
        await session.execute(
            select(ExtractorAuthoringTask).where(
                ExtractorAuthoringTask.source_id.in_(list(source_ids))
            )
        )
    ).scalars().all()
    return {row.source_id: row for row in rows}


async def _should_skip_task(task: ExtractorAuthoringTask | None) -> bool:
    """A task is skipped if it has already reached a terminal state."""
    if task is None:
        return False
    return task.status in {
        AuthoringTaskStatus.DEPLOYED.value,
        AuthoringTaskStatus.AWAITING_REVIEW.value,
    }


async def _mosque_name(session: AsyncSession, source: MosqueSource) -> str:
    if source.mosque_id is None:
        return source.display_name or "Unknown mosque"
    mosque = await session.get(Mosque, source.mosque_id)
    if mosque is None:
        return source.display_name or "Unknown mosque"
    return mosque.name


def _classify_target(discovery: DiscoveryResult) -> AuthoringTargetKind:
    if discovery.target_kind != AuthoringTargetKind.HTML:
        return discovery.target_kind
    return looks_like_javascript_widget(
        sample_text=discovery.sample_text, sample_html=""
    )


def _build_prompt(
    *,
    source_id: str,
    mosque_name: str,
    website_url: str,
    extractor_key: str,
    target_url: str,
    sample_text: str,
    target_kind: AuthoringTargetKind,
) -> str:
    base = build_authoring_prompt(
        source_id=source_id,
        mosque_name=mosque_name,
        website_url=website_url,
        extractor_key=extractor_key,
        max_pages=3,
    )
    extra = (
        "\n\n"
        f"---\n"
        f"Discovered timetable URL: {target_url}\n"
        f"Target kind: {target_kind.value}\n"
        f"Sample (already trimmed, max 16 KB of body text):\n"
        f"```\n{sample_text[:16000]}\n```\n"
        f"---\n"
        f"Author a single Python file at "
        f"`src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts/{extractor_key}.py`. "
        f"When you are done, print a short summary and finish. Do not run any other tools."
    )
    return base + extra


def _classify_target(discovery: DiscoveryResult) -> AuthoringTargetKind:
    if discovery.target_kind != AuthoringTargetKind.HTML:
        return discovery.target_kind
    return looks_like_javascript_widget(
        sample_text=discovery.sample_text, sample_html=""
    )


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


async def _process_source(
    *,
    source: MosqueSource,
    mosque_name: str,
    settings: Settings,
    dry_run: bool,
) -> _SourceProcessResult:
    extractor_key = _safe_extractor_key(
        f"{mosque_name.replace(' ', '_')}_{str(source.id)[:8]}"
    )
    extractor_key = extractor_key or f"source_{str(source.id)[:8]}"
    extractor_version = datetime.now(UTC).strftime("%Y.%m.%d.1")

    discovery: DiscoveryResult = await discover_timetable_url(
        source_url=source.source_url or "",
        settings=settings,
    )
    if discovery.error or discovery.discovered_url is None:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=discovery.error or "no candidates",
            discovered_url=None,
            target_kind=discovery.target_kind.value,
        )
    target_kind = _classify_target(discovery)

    if target_kind in {
        AuthoringTargetKind.PDF,
        AuthoringTargetKind.IMAGE,
        AuthoringTargetKind.RENDERED_HTML,
        AuthoringTargetKind.JSON,
        AuthoringTargetKind.UNKNOWN,
    }:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.SKIPPED_REVIEW.value,
            error=f"{target_kind.value} target not yet supported (ocr/render/json not implemented)",
            discovered_url=discovery.discovered_url,
            target_kind=target_kind.value,
        )

    if not is_opencode_available():
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error="opencode binary not found on PATH",
            discovered_url=discovery.discovered_url,
            target_kind=target_kind.value,
        )

    prompt = _build_prompt(
        source_id=str(source.id),
        mosque_name=mosque_name,
        website_url=source.source_url or "",
        extractor_key=extractor_key,
        target_url=discovery.discovered_url,
        sample_text=discovery.sample_text,
        target_kind=target_kind,
    )
    try:
        agent_result = await run_authoring_agent(prompt=prompt, settings=settings)
    except TimeoutError as exc:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=str(exc),
            discovered_url=discovery.discovered_url,
            target_kind=target_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    source_text = extract_python_block(agent_result.text) or agent_result.text
    issues = validate_draft_source(source_text)
    if issues:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error="; ".join(issues),
            discovered_url=discovery.discovered_url,
            target_kind=target_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
            validation_issues=issues,
            agent_model=settings.ai_agent_model,
            agent_command=agent_result.command,
            agent_duration_ms=agent_result.duration_ms,
            agent_stdout_excerpt=agent_result.stdout_excerpt,
        )

    if dry_run:
        return _SourceProcessResult(
            status=AuthoringTaskStatus.AWAITING_REVIEW.value,
            discovered_url=discovery.discovered_url,
            target_kind=target_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
            validation_issues=[],
            agent_model=settings.ai_agent_model,
            agent_command=agent_result.command,
            agent_duration_ms=agent_result.duration_ms,
            agent_stdout_excerpt=agent_result.stdout_excerpt,
        )

    scripts_dir = _scripts_filesystem_path()
    script_path = write_draft_to_scripts(
        extractor_key=extractor_key,
        source=source_text,
        scripts_dir=scripts_dir,
    )
    return _SourceProcessResult(
        status=AuthoringTaskStatus.AWAITING_REVIEW.value,
        discovered_url=discovery.discovered_url,
        target_kind=target_kind.value,
        extractor_key=extractor_key,
        extractor_version=extractor_version,
        script_path=script_path,
        validation_issues=[],
        agent_model=settings.ai_agent_model,
        agent_command=agent_result.command,
        agent_duration_ms=agent_result.duration_ms,
        agent_stdout_excerpt=agent_result.stdout_excerpt,
    )


async def _run_post_sync(
    session: AsyncSession, *, source_id: uuid.UUID
) -> tuple[str, str | None]:
    """Run :func:`sync_repo_extractors` for one source and return the assignment state."""
    sync_result = await sync_repo_extractors(session, source_id=source_id)
    assignment = await session.get(SourceExtractorAssignment, source_id)
    if assignment is None:
        return (
            AuthoringTaskStatus.FAILED.value,
            "; ".join(sync_result.invalid) or "no assignment created",
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
        try:
            result = await asyncio.wait_for(
                _process_source(
                    source=source,
                    mosque_name=await _mosque_name(session, source),
                    settings=settings,
                    dry_run=dry_run,
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

        task = (
            await session.execute(
                select(ExtractorAuthoringTask).where(
                    ExtractorAuthoringTask.source_id == source.id
                )
            )
        ).scalar_one_or_none()
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

        if result.status == AuthoringTaskStatus.AWAITING_REVIEW.value and not dry_run:
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
