"""Overnight extractor authoring orchestrator.

The orchestrator hands each ``mosque_website`` source to the OpenCode CLI
as a subprocess and lets the agent navigate the source's registrable
domain to find the prayer-timetable page and write a repo extractor script.

Flow per source (concurrent, semaphore-bounded):

1. Domain policy: aggregator sources fail immediately; umbrella (multi-
   mosque) sources go to the review queue. No agent call happens.
2. ``preflight_source`` confirms the source URL is reachable; failures are
   classified (dead site / robots / transient) for resume.
3. The agent navigates the site and either writes the script or reports
   ``skipped_review`` / ``failed`` via the result JSON file.
4. Authored scripts pass static gates, then an execution **smoke test**
   (fetch the declared targets once, run the sandbox, check the output
   structurally and semantically). On smoke/static failure the agent is
   re-invoked with a repair prompt up to ``authoring_max_repair_attempts``
   times.
5. Passing scripts are deployed with an explicit ``(source_id,
   extractor_key)`` assignment binding — no domain-inference matching.

Resume: tasks carry ``failure_category`` and ``attempts``. Permanent
categories (no jamaat times, dead site, robots, aggregator, umbrella) are
skipped on re-runs; retryable categories are re-attempted until
``authoring_max_attempts``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import (
    PERMANENT_FAILURE_CATEGORIES,
    AuthoringFailureCategory,
    AuthoringTargetKind,
    AuthoringTaskStatus,
    SourceType,
)
from uk_jamaat_directory.ingest.authoring.agent import run_authoring_agent
from uk_jamaat_directory.ingest.authoring.authoring_prompt import (
    build_authoring_prompt,
    build_repair_prompt,
)
from uk_jamaat_directory.ingest.authoring.authoring_result import (
    AgentResult,
    authoring_result_path,
    clean_authoring_result,
)
from uk_jamaat_directory.ingest.authoring.backends import get_agent_backend
from uk_jamaat_directory.ingest.authoring.discovery import preflight_source
from uk_jamaat_directory.ingest.authoring.failure_taxonomy import classify_failure
from uk_jamaat_directory.ingest.authoring.smoke_test import smoke_test_extractor
from uk_jamaat_directory.ingest.authoring.validator_post import (
    validate_draft_source,
    write_draft_to_scripts,
)
from uk_jamaat_directory.ingest.domain_policy import (
    is_aggregator_domain,
    is_umbrella_domain,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.sync import (
    deploy_extractor_assignment,
)
from uk_jamaat_directory.ingest.normalize import normalize_domain
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    MosqueSource,
    SourceExtractorAssignment,
)

logger = logging.getLogger(__name__)

SCRIPTS_PACKAGE = "uk_jamaat_directory.ingest.extract.repo_extractors.scripts"
SCRIPTS_DIR = "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts"

MAX_TRACKED_ERRORS = 50


@dataclass
class OrchestrationSummary:
    candidates: int = 0
    preflight_ok: int = 0
    authored: int = 0
    deployed: int = 0
    skipped_review: int = 0
    failed: int = 0
    errors: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_TRACKED_ERRORS))
    errors_total: int = 0
    failure_categories: dict[str, int] = field(default_factory=dict)
    timed_out_global: int = 0
    start_time: float = field(default_factory=time.monotonic)
    processed: int = 0
    in_flight: int = 0

    def as_dict(self) -> dict[str, object]:
        elapsed = time.monotonic() - self.start_time
        return {
            "candidates": self.candidates,
            "preflight_ok": self.preflight_ok,
            "authored": self.authored,
            "deployed": self.deployed,
            "skipped_review": self.skipped_review,
            "failed": self.failed,
            "processed": self.processed,
            "in_flight": self.in_flight,
            "elapsed_seconds": round(elapsed, 1),
            "errors": list(self.errors),
            "errors_total": self.errors_total,
            "failure_categories": dict(sorted(self.failure_categories.items())),
            "timed_out_global": self.timed_out_global,
        }


def _safe_extractor_key(value: str) -> str:
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
        os.path.abspath(os.path.join(os.getcwd(), SCRIPTS_DIR)),
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
    if os.path.isdir(os.path.join(cwd, "src")):
        return cwd
    parent = os.path.dirname(cwd)
    if os.path.isdir(os.path.join(parent, "src")):
        return parent
    return cwd


def _task_eligible_for_retry(
    task: ExtractorAuthoringTask,
    *,
    retry_failed: bool,
    retry_categories: set[str],
    max_attempts: int,
) -> bool:
    if task.status != AuthoringTaskStatus.FAILED.value:
        return False
    if retry_failed:
        return True
    category = task.failure_category
    if category in retry_categories:
        return True
    if category in PERMANENT_FAILURE_CATEGORIES:
        return False
    return (task.attempts or 0) < max_attempts


async def _list_candidate_sources(
    session: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
    retry_categories: set[str] | None = None,
    max_attempts: int = 3,
) -> list[MosqueSource]:
    retry_categories = retry_categories or set()
    stmt = (
        select(MosqueSource, SourceExtractorAssignment, ExtractorAuthoringTask)
        .outerjoin(
            SourceExtractorAssignment,
            SourceExtractorAssignment.source_id == MosqueSource.id,
        )
        .outerjoin(
            ExtractorAuthoringTask,
            ExtractorAuthoringTask.source_id == MosqueSource.id,
        )
        .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
        .where(MosqueSource.source_url.is_not(None))
    )
    if source_id is not None:
        stmt = stmt.where(MosqueSource.id == source_id)
    rows = (await session.execute(stmt)).all()
    eligible: list[MosqueSource] = []
    for source, assignment, task in rows:
        metadata = source.metadata_ or {}
        if metadata.get("crawl_enabled") is False:
            continue
        if assignment is not None and assignment.status == "active":
            continue
        if task is not None:
            if task.status in {
                AuthoringTaskStatus.DEPLOYED.value,
                AuthoringTaskStatus.AWAITING_REVIEW.value,
                AuthoringTaskStatus.SKIPPED_REVIEW.value,
            }:
                continue
            if task.status == AuthoringTaskStatus.FAILED.value and not _task_eligible_for_retry(
                task,
                retry_failed=retry_failed,
                retry_categories=retry_categories,
                max_attempts=max_attempts,
            ):
                continue
        eligible.append(source)
        if limit is not None and source_id is None and len(eligible) >= limit:
            break
    return eligible


async def _existing_task(
    session: AsyncSession, source_id: uuid.UUID
) -> ExtractorAuthoringTask | None:
    return (
        await session.execute(
            select(ExtractorAuthoringTask).where(ExtractorAuthoringTask.source_id == source_id)
        )
    ).scalar_one_or_none()


async def _mosque_name(session: AsyncSession, source: MosqueSource) -> str:
    if source.mosque_id is None:
        return source.display_name or "Unknown mosque"
    mosque = await session.get(Mosque, source.mosque_id)
    if mosque is None:
        return source.display_name or "Unknown mosque"
    return mosque.name


@dataclass
class _SourceProcessResult:
    status: str
    error: str | None = None
    failure_category: str | None = None
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
    repair_attempts: int = 0
    smoke_report: dict[str, object] | None = None


def _read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _resolve_script_absolute_path(script_path: str) -> str | None:
    """Turn the agent's reported script path (repo-relative or absolute)
    into an absolute path the orchestrator can read."""

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
    base = _SourceProcessResult(
        status=AuthoringTaskStatus.FAILED.value,
        discovered_url=report.target_url or source.source_url,
        target_kind=(
            report.target_kind.value
            if report.target_kind is not None
            else AuthoringTargetKind.UNKNOWN.value
        ),
        extractor_key=extractor_key,
        extractor_version=datetime.now(UTC).strftime("%Y.%m.%d.1"),
        agent_command=agent_result.command,
        agent_duration_ms=agent_result.duration_ms,
        agent_stdout_excerpt=agent_result.stdout_excerpt,
    )

    if not report.status:
        base.error = report.reason or "agent did not report a status"
        base.failure_category = AuthoringFailureCategory.AGENT_ERROR.value
        return base
    status = report.status.lower().strip()

    if status == "skipped_review":
        base.status = AuthoringTaskStatus.SKIPPED_REVIEW.value
        base.error = report.reason or "skipped by agent (no reason given)"
        return base

    if status == "failed":
        base.status = AuthoringTaskStatus.FAILED.value
        base.error = report.reason or "agent reported failure (no reason given)"
        base.failure_category = classify_failure(agent_reason=base.error).value
        return base

    if status != "authored":
        base.error = f"agent reported unknown status: {status!r}"
        base.failure_category = AuthoringFailureCategory.AGENT_ERROR.value
        return base

    if not report.script_path:
        base.error = "agent reported authored but no script_path"
        base.failure_category = AuthoringFailureCategory.AGENT_ERROR.value
        return base
    absolute = _resolve_script_absolute_path(report.script_path)
    if absolute is None or not os.path.isfile(absolute):
        base.error = f"script not found at {report.script_path}"
        base.failure_category = AuthoringFailureCategory.AGENT_ERROR.value
        return base

    source_text = _read_text_file(absolute)
    if source_text is None:
        base.error = f"could not read script at {absolute}"
        base.failure_category = AuthoringFailureCategory.AGENT_ERROR.value
        return base

    issues = validate_draft_source(source_text)
    if issues:
        base.validation_issues = issues
        base.script_path = absolute
        base.error = "; ".join(issues)
        base.failure_category = AuthoringFailureCategory.VALIDATION_FAILED.value
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


async def _process_one(
    *,
    session_factory: async_sessionmaker,
    source: MosqueSource,
    semaphore: asyncio.Semaphore,
    summary: OrchestrationSummary,
    dry_run: bool,
    settings: Settings,
    progress_lock: asyncio.Lock,
    on_progress: Callable[[OrchestrationSummary], Awaitable[None]] | None,
) -> None:
    async with semaphore:
        async with progress_lock:
            summary.in_flight += 1
        started = time.monotonic()
        task_status = AuthoringTaskStatus.FAILED.value
        task_error: str | None = None
        task_category: str | None = AuthoringFailureCategory.AGENT_ERROR.value
        try:
            async with session_factory() as session:
                result = await _process_source(session=session, source=source, settings=settings)

                task = await _existing_task(session, source.id)
                if task is None:
                    task = ExtractorAuthoringTask(id=uuid.uuid4(), source_id=source.id)
                    session.add(task)
                task.status = result.status
                task.discovered_url = result.discovered_url
                task.target_kind = result.target_kind
                task.extractor_key = result.extractor_key
                task.extractor_version = result.extractor_version
                task.script_path = result.script_path
                task.validation_issues = [{"issue": issue} for issue in result.validation_issues]
                task.agent_model = result.agent_model
                task.agent_command = result.agent_command
                task.agent_duration_ms = result.agent_duration_ms
                task.agent_stdout_excerpt = result.agent_stdout_excerpt
                task.error = result.error
                task.failure_category = result.failure_category
                task.attempts = (task.attempts or 0) + 1
                task.last_attempt_at = datetime.now(UTC)
                task.started_at = datetime.now(UTC)
                task.finished_at = datetime.now(UTC)
                task.metadata_ = {
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "source_url": source.source_url,
                    "repair_attempts": result.repair_attempts,
                }
                if result.smoke_report is not None:
                    task.metadata_["smoke"] = result.smoke_report

                if not dry_run and result.status == AuthoringTaskStatus.AWAITING_REVIEW.value:
                    try:
                        deployed, issues = await deploy_extractor_assignment(
                            session,
                            source_id=source.id,
                            extractor_key=result.extractor_key or "",
                        )
                        if deployed:
                            task.status = AuthoringTaskStatus.DEPLOYED.value
                            task.failure_category = None
                        else:
                            task.status = AuthoringTaskStatus.FAILED.value
                            task.error = "; ".join(issues) or "no assignment created"
                            task.failure_category = (
                                AuthoringFailureCategory.VALIDATION_FAILED.value
                            )
                    except Exception as post_exc:
                        logger.exception("deploy failed for source %s", source.id)
                        task.status = AuthoringTaskStatus.FAILED.value
                        task.error = f"deploy failed: {post_exc}"
                        task.failure_category = AuthoringFailureCategory.AGENT_ERROR.value

                await session.commit()
                task_status = task.status
                task_error = task.error
                task_category = task.failure_category
        except Exception as exc:
            logger.exception("unhandled exception processing source %s", source.id)
            task_error = f"unhandled exception: {exc}"
            try:
                async with session_factory() as session:
                    task = await _existing_task(session, source.id)
                    if task is None:
                        task = ExtractorAuthoringTask(id=uuid.uuid4(), source_id=source.id)
                        session.add(task)
                    task.status = AuthoringTaskStatus.FAILED.value
                    task.error = task_error
                    task.failure_category = AuthoringFailureCategory.AGENT_ERROR.value
                    task.attempts = (task.attempts or 0) + 1
                    task.last_attempt_at = datetime.now(UTC)
                    task.started_at = datetime.now(UTC)
                    task.finished_at = datetime.now(UTC)
                    task.metadata_ = {"source_url": source.source_url}
                    await session.commit()
            except Exception:
                logger.exception(
                    "failed to persist failure task for source %s", source.id
                )

        # The per-source result JSON is fully captured on the task row; drop
        # the file so data/authoring_results does not accumulate stale state.
        clean_authoring_result(authoring_result_path(source.id))

        async with progress_lock:
            summary.in_flight -= 1
            if task_status == AuthoringTaskStatus.DEPLOYED.value:
                summary.deployed += 1
                summary.preflight_ok += 1
            elif task_status == AuthoringTaskStatus.AWAITING_REVIEW.value:
                summary.authored += 1
                summary.preflight_ok += 1
            elif task_status == AuthoringTaskStatus.SKIPPED_REVIEW.value:
                summary.skipped_review += 1
                summary.preflight_ok += 1
            else:
                summary.failed += 1
                if task_category:
                    summary.failure_categories[task_category] = (
                        summary.failure_categories.get(task_category, 0) + 1
                    )
            summary.processed += 1
            if task_error:
                summary.errors.append(f"{source.id}: {task_error[:200]}")
                summary.errors_total += 1
            if on_progress is not None:
                await on_progress(summary)


def _registry_entry_for_module(module_short: str):
    """Find the loaded extractor whose script file is ``<module_short>.py``.

    The agent controls the ``key`` attribute inside the script, which may
    differ from the filename the orchestrator chose; the file location is
    the reliable link."""
    from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
        load_all_extractors,
    )

    for entry in load_all_extractors(reload=True):
        if entry.module_name.rsplit(".", 1)[-1] == module_short:
            return entry
    return None


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
    domain = normalize_domain(source.source_url)

    # Domain policy gates: no agent call for aggregator/umbrella sources.
    if is_aggregator_domain(domain, settings=settings):
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=f"source domain {domain} is a directory/aggregator site",
            failure_category=AuthoringFailureCategory.AGGREGATOR.value,
            discovered_url=source.source_url,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )
    if is_umbrella_domain(domain, settings=settings):
        return _SourceProcessResult(
            status=AuthoringTaskStatus.SKIPPED_REVIEW.value,
            error=(
                f"source domain {domain} is a multi-mosque umbrella site — "
                "needs manual review"
            ),
            failure_category=AuthoringFailureCategory.UMBRELLA_REVIEW.value,
            discovered_url=source.source_url,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    preflight = await preflight_source(source_url=source.source_url or "", settings=settings)
    if not preflight.reachable:
        error = preflight.error or "preflight: source unreachable"
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=error,
            failure_category=classify_failure(preflight_error=error).value,
            target_kind=preflight.predicted_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    backend = get_agent_backend(settings)
    if not backend.is_available():
        return _SourceProcessResult(
            status=AuthoringTaskStatus.FAILED.value,
            error=f"agent binary {backend.binary!r} (backend {backend.name!r}) not found on PATH",
            failure_category=AuthoringFailureCategory.AGENT_ERROR.value,
            discovered_url=source.source_url,
            target_kind=preflight.predicted_kind.value,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
        )

    scripts_dir = _scripts_filesystem_path()
    script_path = os.path.join(scripts_dir, f"{extractor_key}.py")
    result_path = authoring_result_path(source.id)

    prompt = build_authoring_prompt(
        source_id=str(source.id),
        mosque_name=mosque_name,
        website_url=source.source_url or "",
        extractor_key=extractor_key,
        script_path=os.path.relpath(script_path, _repo_root()),
        result_path=os.path.relpath(result_path, _repo_root()),
        domain=preflight.domain or domain or "",
        predicted_kind=preflight.predicted_kind,
        max_pages=8,
    )

    max_repairs = max(0, settings.authoring_max_repair_attempts)
    repair_attempts = 0
    result: _SourceProcessResult | None = None

    while True:
        clean_authoring_result(result_path)
        try:
            agent_result: AgentResult = await run_authoring_agent(
                prompt=prompt,
                settings=settings,
                result_path=result_path,
                cwd=_repo_root(),
                backend=backend,
            )
        except TimeoutError as exc:
            return _SourceProcessResult(
                status=AuthoringTaskStatus.FAILED.value,
                error=str(exc),
                failure_category=AuthoringFailureCategory.TIMEOUT.value,
                discovered_url=source.source_url,
                target_kind=preflight.predicted_kind.value,
                extractor_key=extractor_key,
                extractor_version=extractor_version,
                repair_attempts=repair_attempts,
            )

        result = _classify_agent_result(
            agent_result=agent_result,
            source=source,
            extractor_key=extractor_key,
            scripts_dir=scripts_dir,
        )
        result.agent_model = backend.resolve_model(settings)
        result.repair_attempts = repair_attempts

        issues: list[str] = []
        if result.status == AuthoringTaskStatus.AWAITING_REVIEW.value:
            entry = _registry_entry_for_module(extractor_key)
            if entry is None:
                result.status = AuthoringTaskStatus.FAILED.value
                result.error = "script did not register a loadable Extractor class"
                result.failure_category = AuthoringFailureCategory.VALIDATION_FAILED.value
                issues = [result.error]
            else:
                # Use the key/version the script actually declares.
                result.extractor_key = entry.extractor.key
                result.extractor_version = entry.extractor.version
        if result.status == AuthoringTaskStatus.AWAITING_REVIEW.value:
            if not settings.authoring_smoke_test_enabled:
                return result
            smoke = await smoke_test_extractor(
                extractor_key=result.extractor_key or extractor_key,
                source_url=source.source_url or "",
                mosque_name=mosque_name,
                settings=settings,
            )
            result.smoke_report = smoke.as_dict()
            if smoke.ok:
                return result
            issues = smoke.issues
            result.status = AuthoringTaskStatus.FAILED.value
            result.error = "smoke test failed: " + "; ".join(issues)[:500]
            result.failure_category = AuthoringFailureCategory.VALIDATION_FAILED.value
        elif result.validation_issues and result.script_path:
            issues = result.validation_issues
        else:
            return result

        if repair_attempts >= max_repairs:
            result.validation_issues = issues
            return result

        repair_attempts += 1
        prompt = build_repair_prompt(
            mosque_name=mosque_name,
            extractor_key=extractor_key,
            script_path=os.path.relpath(result.script_path or script_path, _repo_root()),
            result_path=os.path.relpath(result_path, _repo_root()),
            source_url=source.source_url or "",
            issues=issues,
            attempt=repair_attempts,
        )


async def run_overnight_orchestrator(
    *,
    session: AsyncSession,
    settings: Settings | None = None,
    source_id: uuid.UUID | None = None,
    limit: int | None = None,
    concurrency: int | None = None,
    dry_run: bool = False,
    retry_failed: bool = False,
    retry_categories: set[str] | None = None,
    max_attempts: int | None = None,
    on_progress: Callable[[OrchestrationSummary], Awaitable[None]] | None = None,
) -> OrchestrationSummary:
    cfg = settings or get_settings()
    workers = max(1, concurrency or cfg.authoring_concurrency)
    semaphore = asyncio.Semaphore(workers)
    summary = OrchestrationSummary()

    sources = await _list_candidate_sources(
        session,
        source_id=source_id,
        limit=limit,
        retry_failed=retry_failed,
        retry_categories=retry_categories,
        max_attempts=max_attempts if max_attempts is not None else cfg.authoring_max_attempts,
    )
    summary.candidates = len(sources)
    if on_progress is not None:
        await on_progress(summary)
    if not sources:
        return summary

    await session.commit()
    engine = session.bind
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    progress_lock = asyncio.Lock()

    tasks = [
        asyncio.create_task(
            _process_one(
                session_factory=session_factory,
                source=source,
                semaphore=semaphore,
                summary=summary,
                dry_run=dry_run,
                settings=cfg,
                progress_lock=progress_lock,
                on_progress=on_progress,
            )
        )
        for source in sources
    ]
    heartbeat: asyncio.Task | None = None
    if on_progress is not None:

        async def _heartbeat() -> None:
            # Sources take minutes each; emit progress between completions so
            # operators can see the run is alive (in_flight, elapsed, eta).
            while True:
                await asyncio.sleep(30)
                async with progress_lock:
                    await on_progress(summary)

        heartbeat = asyncio.create_task(_heartbeat())

    done, pending = await asyncio.wait(
        tasks, timeout=cfg.authoring_global_timeout_seconds or None
    )
    if heartbeat is not None:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
    if pending:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        async with progress_lock:
            summary.timed_out_global = len(pending)
            summary.errors.append(
                f"global timeout: {len(pending)} source(s) cancelled after "
                f"{cfg.authoring_global_timeout_seconds:.0f}s"
            )
            summary.errors_total += 1
    if on_progress is not None:
        await on_progress(summary)
    return summary
