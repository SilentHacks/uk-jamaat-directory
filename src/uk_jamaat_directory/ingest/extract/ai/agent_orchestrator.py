from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.domain import ExtractionKind, SourceType
from uk_jamaat_directory.ingest.extract.ai.agent_prompt import build_agent_prompt
from uk_jamaat_directory.ingest.extract.ai.agent_result import AgentResult, parse_agent_result
from uk_jamaat_directory.ingest.extract.ai.profile import ExtractionProfile
from uk_jamaat_directory.models.core import ExtractionRun, Mosque, MosqueSource


@dataclass
class AgentOrchestratorResult:
    """Result of an agent profiling orchestration run."""

    attempted: int = 0
    succeeded: int = 0
    review_needed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    output_dir: Path | None = None


@dataclass
class _SourceJob:
    source_id: uuid.UUID
    mosque_name: str
    website_url: str
    output_dir: Path
    result_path: Path
    session_log_path: Path


def _log(output_dir: Path, level: str, message: str) -> None:
    """Append a structured log line to orchestrator.log."""
    log_path = output_dir / "orchestrator.log"
    ts = datetime.now(UTC).isoformat()
    line = f"{ts} [{level}] {message}\n"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def _save_metrics(
    output_dir: Path,
    total: int,
    completed: int,
    failed: int,
    in_progress: int,
    started_at: float,
) -> None:
    """Write a metrics.json with real-time progress and ETA."""
    metrics: dict[str, Any] = {
        "updated_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started_at, 1),
        "total_sources": total,
        "completed": completed,
        "failed": failed,
        "in_progress": in_progress,
        "remaining": total - completed - failed,
    }
    elapsed = metrics["elapsed_seconds"]
    processed = completed + failed
    if processed > 0 and elapsed > 0:
        avg = elapsed / processed
        metrics["avg_seconds_per_source"] = round(avg, 1)
        metrics["estimated_seconds_remaining"] = round(avg * metrics["remaining"], 1)
    else:
        metrics["avg_seconds_per_source"] = None
        metrics["estimated_seconds_remaining"] = None
    path = output_dir / "metrics.json"
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def _init_state(output_dir: Path) -> dict[str, Any]:
    state: dict[str, Any] = {
        "run_id": datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        "started_at": datetime.now(UTC).isoformat(),
        "completed": [],
        "failed": {},
        "in_progress": [],
    }
    _save_state(output_dir, state)
    return state


def _save_state(output_dir: Path, state: dict[str, Any]) -> None:
    path = output_dir / "state.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _load_state(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def _spawn_agent(
    job: _SourceJob,
    settings: Settings,
    max_pages: int,
    timeout: float,
) -> AgentResult | None:
    """Spawn an opencode agent subprocess and return its parsed result.

    Returns ``None`` if the result file is missing or the agent timed out.
    """
    prompt = build_agent_prompt(
        mosque_name=job.mosque_name,
        website_url=job.website_url,
        output_path=str(job.result_path),
        max_pages=max_pages,
    )

    cmd = [
        "opencode",
        "-m",
        settings.ai_agent_model,
        "run",
        "--dangerously-skip-permissions",
        "--dir",
        str(job.output_dir),
        prompt,
    ]

    # Ensure output directory exists before the agent starts
    job.output_dir.mkdir(parents=True, exist_ok=True)

    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait with timeout
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except TimeoutError:
            # Kill the agent on timeout
            if proc.returncode is None:
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    pass
            return None

        # Capture logs for debugging
        if proc.stdout:
            stdout_data = await proc.stdout.read()
            job.session_log_path.write_bytes(stdout_data)
        if proc.stderr:
            stderr_data = await proc.stderr.read()
            # Append stderr to log
            with job.session_log_path.open("ab") as f:
                f.write(b"\n--- STDERR ---\n")
                f.write(stderr_data)

    except Exception:
        if proc is not None and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except TimeoutError:
                pass
        return None
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()

    # Parse the result file written by the agent
    return parse_agent_result(job.result_path)


async def _commit_profile(
    session: AsyncSession,
    source_id: uuid.UUID,
    agent_result: AgentResult,
    settings: Settings,
) -> str:
    """Write an agent result into the database.

    Returns the profile status string ("ready", "review_needed", or "failed").
    """
    source = await session.get(MosqueSource, source_id)
    if source is None:
        return "failed"

    profile = agent_result.profile

    # Determine profile status
    profile_status = "review_needed"
    if profile.found and profile.confidence >= 0.8 and profile.asset_type != "unknown":
        profile_status = "ready"
    elif not profile.found:
        profile_status = "review_needed"

    # Update source metadata
    metadata = dict(source.metadata_ or {})
    metadata["extraction_profile"] = profile.model_dump(mode="json")
    metadata["profile_status"] = profile_status
    metadata["profile_model"] = settings.ai_agent_model
    metadata["profiled_at"] = datetime.now(UTC).isoformat()
    metadata["profile_version"] = profile.profile_version
    source.metadata_ = metadata

    # Create extraction run for audit trail
    run = ExtractionRun(
        id=uuid.uuid4(),
        artifact_id=None,
        source_id=source.id,
        kind=ExtractionKind.AI,
        extractor_version=f"agent-{settings.ai_agent_model}/v2",
        status="succeeded",
        score=profile.confidence,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata_={
            "pages_fetched": profile.pages_fetched,
            "urls_explored": profile.urls_explored,
            "navigation_log": profile.navigation_log,
            "found": profile.found,
            "model": settings.ai_agent_model,
            "raw_profile": agent_result.raw_json,
            "parse_errors": agent_result.parse_errors,
        },
    )
    session.add(run)
    await session.flush()

    return profile_status


async def run_agent_profiling(
    session: AsyncSession,
    settings: Settings,
    *,
    limit: int = 50,
    concurrency: int = 3,
    timeout: float = 120.0,
    max_pages: int = 10,
    output_dir: Path | None = None,
    force: bool = False,
) -> AgentOrchestratorResult:
    """Orchestrate autonomous agent profiling for unprofiled mosque website sources.

    Queries the database for ``MOSQUE_WEBSITE`` sources, spawns opencode agents
    concurrently, collects JSON result files, and commits profiles to the database.

    Args:
        session: Async SQLAlchemy session.
        settings: Project settings.
        limit: Maximum number of sources to profile in this run.
        concurrency: Maximum number of concurrent agent subprocesses.
        timeout: Maximum seconds to wait for each agent.
        max_pages: Maximum pages the agent may fetch per source.
        output_dir: Directory to store agent result files and session logs.
            Defaults to ``data/agent_profiles/<timestamp>``.
        force: Profile even sources that already have a ``ready`` profile.

    Returns:
        ``AgentOrchestratorResult`` with counts and any errors.
    """
    result = AgentOrchestratorResult()

    if not settings.ai_profiling_enabled:
        result.errors.append("ai_profiling_enabled is False; skipping")
        return result

    if output_dir is None:
        output_dir = Path("data/agent_profiles") / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    result.output_dir = output_dir

    # Load or init state
    state = _load_state(output_dir)
    if state is None:
        state = _init_state(output_dir)

    # Query eligible sources
    stmt = (
        sa_select(MosqueSource, Mosque)
        .join(Mosque, MosqueSource.mosque_id == Mosque.id)
        .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
        .where(MosqueSource.source_url.is_not(None))
    )
    if not force:
        stmt = stmt.where(MosqueSource.metadata_["profile_status"].astext != "ready")
    stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()

    # Filter out already-completed sources from a resumed run
    completed_ids = {uuid.UUID(sid) for sid in state["completed"]}
    failed_ids = {uuid.UUID(sid) for sid in state["failed"]}

    jobs: list[_SourceJob] = []
    for source, mosque in rows:
        if source.id in completed_ids:
            continue
        if source.id in failed_ids:
            continue
        job_dir = output_dir / str(source.id)
        jobs.append(
            _SourceJob(
                source_id=source.id,
                mosque_name=mosque.name,
                website_url=source.source_url or "",
                output_dir=job_dir,
                result_path=job_dir / "result.json",
                session_log_path=job_dir / "session.log",
            )
        )

    if not jobs:
        result.errors.append("No eligible sources found to profile")
        _log(output_dir, "WARN", "No eligible sources found to profile")
        return result

    total_jobs = len(jobs)
    started_at = time.monotonic()
    _log(
        output_dir, "INFO",
        f"Starting batch: limit={limit}, concurrency={concurrency}, timeout={timeout}s",
    )
    _log(output_dir, "INFO", f"Enqueued {total_jobs} sources for profiling")

    semaphore = asyncio.Semaphore(concurrency)
    metrics_task: asyncio.Task | None = None

    async def _metrics_loop() -> None:
        while True:
            await asyncio.sleep(10)
            completed = len(state["completed"])
            failed = len(state["failed"])
            in_progress = len(state["in_progress"])
            _save_metrics(
                output_dir, total_jobs, completed, failed, in_progress, started_at,
            )

    metrics_task = asyncio.create_task(_metrics_loop())

    async def _run_one(job: _SourceJob) -> None:
        async with semaphore:
            start = time.monotonic()
            _log(
                output_dir, "INFO",
                f"Agent spawned: source={job.source_id}, mosque={job.mosque_name}",
            )
            state["in_progress"].append(str(job.source_id))
            _save_state(output_dir, state)

            agent_result = await _spawn_agent(
                job, settings, max_pages=max_pages, timeout=timeout
            )

            state["in_progress"].remove(str(job.source_id))
            elapsed = round(time.monotonic() - start, 1)

            if agent_result is None:
                _log(
                    output_dir, "WARN",
                    f"Agent timed out: source={job.source_id}, elapsed={elapsed}s",
                )
                state["failed"][str(job.source_id)] = "timeout_or_missing_result"
                _save_state(output_dir, state)
                result.failed += 1
                return

            # Post-hoc domain escape validation
            target_domain = _extract_domain(job.website_url)
            banned_domains = {
                "web.archive.org", "archive.org", "webcache.googleusercontent.com",
            }
            escaped = [
                url
                for url in agent_result.profile.urls_explored
                if not _url_matches_domain(url, target_domain)
            ]
            banned_hits = {
                url for url in escaped if any(bd in url for bd in banned_domains)
            }
            if banned_hits:
                agent_result.profile.found = False
                agent_result.profile.review_notes = (
                    "[AGENT VIOLATION] Agent accessed banned archive sites: "
                    f"{', '.join(sorted(banned_hits))}. "
                    + agent_result.profile.review_notes
                )
                if not agent_result.parse_errors:
                    agent_result.parse_errors.append(
                        "Agent violated domain jail by fetching "
                        f"{len(banned_hits)} banned URL(s)"
                    )

            if agent_result.parse_errors:
                _log(
                    output_dir, "WARN",
                    f"Agent failed: source={job.source_id}, "
                    f"errors={agent_result.parse_errors}",
                )
                state["failed"][str(job.source_id)] = "; ".join(
                    agent_result.parse_errors
                )
                _save_state(output_dir, state)
                result.failed += 1
                return

            async with cli_db_session(settings) as commit_session:
                profile_status = await _commit_profile(
                    commit_session, job.source_id, agent_result, settings
                )
                await commit_session.commit()

            state["completed"].append(str(job.source_id))
            _save_state(output_dir, state)

            _log(
                output_dir, "INFO",
                f"Agent completed: source={job.source_id}, "
                f"status={profile_status}, elapsed={elapsed}s",
            )

            if profile_status == "ready":
                result.succeeded += 1
            else:
                result.review_needed += 1

    result.attempted = len(jobs)
    try:
        await asyncio.gather(*[_run_one(job) for job in jobs])
    finally:
        if metrics_task is not None:
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass
        _save_metrics(
            output_dir,
            total_jobs,
            len(state["completed"]),
            len(state["failed"]),
            len(state["in_progress"]),
            started_at,
        )
        _log(
            output_dir, "INFO",
            "Batch finished: "
            f"attempted={result.attempted}, ready={result.succeeded}, "
            f"review_needed={result.review_needed}, failed={result.failed}",
        )

    return result


async def profile_single_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    settings: Settings,
) -> AgentResult:
    """Profile a single mosque website source with an autonomous agent.

    Convenience wrapper around ``_spawn_agent`` and ``_commit_profile`` for
    the admin API trigger endpoint.

    Args:
        session: Async SQLAlchemy session.
        source_id: UUID of the ``MOSQUE_WEBSITE`` source to profile.
        settings: Project settings.

    Returns:
        ``AgentResult`` with the parsed profile or parse errors.
    """
    source = await session.get(MosqueSource, source_id)
    if source is None:
        return AgentResult(
            profile=ExtractionProfile(review_notes="Source not found"),
            parse_errors=["Source not found"],
        )

    mosque = await session.get(Mosque, source.mosque_id) if source.mosque_id else None
    if mosque is None:
        return AgentResult(
            profile=ExtractionProfile(review_notes="Source is not linked to a mosque"),
            parse_errors=["Source is not linked to a mosque"],
        )

    output_dir = Path("data/agent_profiles") / "single" / str(source_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    job = _SourceJob(
        source_id=source_id,
        mosque_name=mosque.name,
        website_url=source.source_url or "",
        output_dir=output_dir,
        result_path=output_dir / "result.json",
        session_log_path=output_dir / "session.log",
    )

    agent_result = await _spawn_agent(
        job,
        settings,
        max_pages=settings.ai_agent_max_pages,
        timeout=settings.ai_agent_timeout,
    )

    if agent_result is None:
        return AgentResult(
            profile=ExtractionProfile(review_notes="Agent timed out or did not write result"),
            parse_errors=["Agent timed out or did not write result"],
        )

    if agent_result.parse_errors:
        return agent_result

    await _commit_profile(session, source_id, agent_result, settings)
    await session.commit()

    return agent_result


def _extract_domain(url: str) -> str:
    """Extract the domain from a URL for domain-jail checks."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.netloc or url


def _url_matches_domain(url: str, domain: str) -> bool:
    """Check whether a URL belongs to the given domain (or a subdomain of it)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.netloc or ""
    # Exact match or subdomain match
    return host == domain or host.endswith(f".{domain}")
