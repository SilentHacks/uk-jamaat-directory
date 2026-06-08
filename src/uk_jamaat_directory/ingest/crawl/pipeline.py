from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import FreshnessStatus, SourceType
from uk_jamaat_directory.ingest.artifacts import latest_artifact_for_source, record_fetched_artifact
from uk_jamaat_directory.ingest.extract.repo_extractors.runtime import (
    RepoExtractionOutcome,
    _schedule_next_run,
    list_due_repo_extractor_source_ids,
    run_extractor_for_source,
)
from uk_jamaat_directory.ingest.extract.runner import ExtractionRunResult, run_extraction
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    MosqueSource,
    SourceExtractorAssignment,
    SourceHealth,
)


@dataclass
class ProcessSourceResult:
    source_id: uuid.UUID
    fetched: bool = False
    unchanged: bool = False
    artifact_created: bool = False
    extracted: bool = False
    candidates_created: int = 0
    skipped_reason: str | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    extractor_key: str | None = None
    extractor_version: str | None = None
    target_count: int = 0


def _crawl_enabled_for_source(source: MosqueSource, settings: Settings) -> bool:
    if not settings.crawl_enabled:
        return False
    if source.source_type != SourceType.MOSQUE_WEBSITE:
        return False
    return source.metadata_.get("crawl_enabled", True) is not False


def _is_due(source: MosqueSource, *, now: datetime) -> bool:
    raw = source.metadata_.get("next_fetch_at")
    if raw is None:
        return True
    try:
        next_fetch = datetime.fromisoformat(raw)
        if next_fetch.tzinfo is None:
            next_fetch = next_fetch.replace(tzinfo=UTC)
    except ValueError:
        return True
    return next_fetch <= now


def _schedule_next_fetch(
    source: MosqueSource,
    *,
    settings: Settings,
    success: bool,
    failures: int,
) -> None:
    now = datetime.now(UTC)
    if success:
        delta = timedelta(hours=settings.crawl_interval_hours)
    else:
        hours = min(24, 2 ** min(failures, 4))
        delta = timedelta(hours=hours)
    metadata = dict(source.metadata_ or {})
    metadata["next_fetch_at"] = (now + delta).isoformat()
    source.metadata_ = metadata


async def _latest_successful_extraction_for_artifact(
    session: AsyncSession,
    artifact_id: uuid.UUID,
) -> ExtractionRun | None:
    return await session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.artifact_id == artifact_id)
        .where(ExtractionRun.status == "succeeded")
        .order_by(ExtractionRun.finished_at.desc().nullslast(), ExtractionRun.started_at.desc())
        .limit(1)
    )


async def _apply_extraction_result(
    session: AsyncSession,
    source: MosqueSource,
    *,
    settings: Settings,
    result: ProcessSourceResult,
    extraction: ExtractionRunResult,
) -> ProcessSourceResult:
    result.extracted = extraction.status == "succeeded"
    result.candidates_created = extraction.candidates_created
    result.warnings.extend(extraction.warnings)
    if extraction.errors:
        result.error = "; ".join(extraction.errors)
        health = await _touch_source_health(
            session,
            source.id,
            success=False,
            message=result.error,
        )
        _schedule_next_fetch(
            source, settings=settings, success=False, failures=health.consecutive_failures
        )
        await session.flush()
        return result

    await _touch_source_health(
        session,
        source.id,
        success=True,
        message="fetch and extraction completed",
    )
    _schedule_next_fetch(source, settings=settings, success=True, failures=0)
    await session.flush()
    return result


async def _touch_source_health(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    success: bool,
    message: str,
) -> SourceHealth:
    health = await session.get(SourceHealth, source_id)
    if health is None:
        health = SourceHealth(
            source_id=source_id,
            freshness_status=FreshnessStatus.NEEDS_REVIEW,
        )
        session.add(health)

    now = datetime.now(UTC)
    if success:
        health.last_success_at = now
        health.consecutive_failures = 0
        health.message = message
    else:
        health.last_failure_at = now
        health.consecutive_failures = (health.consecutive_failures or 0) + 1
        health.message = message
        if health.consecutive_failures >= 3:
            health.freshness_status = FreshnessStatus.SOURCE_FAILED

    await session.flush()
    return health


async def list_due_source_ids(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> list[uuid.UUID]:
    cfg = settings or get_settings()
    if not cfg.crawl_enabled:
        return []

    repo_due = await list_due_repo_extractor_source_ids(session, settings=cfg)
    if repo_due:
        return repo_due

    now = datetime.now(UTC)
    sources = (
        (
            await session.execute(
                select(MosqueSource.id)
                .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
                .where(MosqueSource.source_url.is_not(None))
            )
        )
        .scalars()
        .all()
    )

    due: list[uuid.UUID] = []
    for source_id in sources:
        source = await session.get(MosqueSource, source_id)
        if source is None:
            continue
        if not _crawl_enabled_for_source(source, cfg):
            continue
        if _is_due(source, now=now):
            due.append(source_id)
    return due


async def _has_active_repo_assignment(
    session: AsyncSession, source_id: uuid.UUID
) -> bool:
    assignment = await session.get(SourceExtractorAssignment, source_id)
    return assignment is not None and assignment.status == "active"


async def _apply_repo_extraction_outcome(
    session: AsyncSession,
    source: MosqueSource,
    *,
    settings: Settings,
    result: ProcessSourceResult,
    outcome: RepoExtractionOutcome,
) -> ProcessSourceResult:
    assignment = await session.get(SourceExtractorAssignment, source.id)
    success = outcome.status == "succeeded"
    result.extracted = success
    result.candidates_created = outcome.rows
    result.extractor_key = outcome.extractor_key or None
    result.extractor_version = outcome.extractor_version or None
    result.target_count = len(outcome.artifact_ids)
    result.warnings.extend(outcome.warnings)
    if outcome.error:
        result.error = outcome.error
    if assignment is not None:
        _schedule_next_run(assignment, success=success)
        if success:
            assignment.last_success_at = datetime.now(UTC)
        else:
            assignment.last_failure_at = datetime.now(UTC)
            assignment.last_error = outcome.error
    health = await _touch_source_health(
        session,
        source.id,
        success=success,
        message=outcome.error or "repo extractor run completed",
    )
    if not success and health.consecutive_failures >= 3 and assignment is not None:
        assignment.status = "failed_validation"
    await session.flush()
    return result


async def process_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> ProcessSourceResult:
    cfg = settings or get_settings()
    result = ProcessSourceResult(source_id=source_id)

    source = await session.get(MosqueSource, source_id)
    if source is None:
        result.error = "source not found"
        return result

    if not _crawl_enabled_for_source(source, cfg):
        result.skipped_reason = "crawl disabled"
        return result

    if await _has_active_repo_assignment(session, source.id):
        outcome = await run_extractor_for_source(session, source, settings=cfg)
        return await _apply_repo_extraction_outcome(
            session, source, settings=cfg, result=result, outcome=outcome
        )

    now = datetime.now(UTC)
    if not force and not _is_due(source, now=now):
        result.skipped_reason = "not due for fetch"
        return result

    if not source.source_url:
        result.error = "source has no source_url"
        health = await _touch_source_health(
            session,
            source.id,
            success=False,
            message=result.error,
        )
        _schedule_next_fetch(
            source, settings=cfg, success=False, failures=health.consecutive_failures
        )
        await session.flush()
        return result

    prior = await latest_artifact_for_source(session, source.id)
    fetch = await fetch_url(source.source_url, prior_artifact=prior, settings=cfg)

    if fetch.error:
        result.error = fetch.error
        health = await _touch_source_health(
            session,
            source.id,
            success=False,
            message=fetch.error,
        )
        _schedule_next_fetch(
            source, settings=cfg, success=False, failures=health.consecutive_failures
        )
        await session.flush()
        return result

    result.fetched = True

    if fetch.unchanged:
        result.unchanged = True
        source.last_seen_at = now
        artifact = prior
        if artifact is None:
            result.error = "unchanged response without prior artifact"
            health = await _touch_source_health(
                session,
                source.id,
                success=False,
                message=result.error,
            )
            _schedule_next_fetch(
                source, settings=cfg, success=False, failures=health.consecutive_failures
            )
            await session.flush()
            return result

        prior_success = await _latest_successful_extraction_for_artifact(session, artifact.id)
        if prior_success is not None:
            await _touch_source_health(
                session,
                source.id,
                success=True,
                message="content unchanged (304 or prior hash)",
            )
            _schedule_next_fetch(source, settings=cfg, success=True, failures=0)
            await session.flush()
            return result

        extraction = await run_extraction(session, artifact, source, settings=cfg)
        return await _apply_extraction_result(
            session,
            source,
            settings=cfg,
            result=result,
            extraction=extraction,
        )

    content_type = fetch.content_type or "application/octet-stream"
    artifact, created, _content_hash = await record_fetched_artifact(
        session,
        source,
        fetched_url=source.source_url,
        body=fetch.body,
        content_type=content_type,
        etag=fetch.etag,
        last_modified=fetch.last_modified,
        upload_to_s3=True,
        settings=cfg,
    )
    result.artifact_created = created
    source.last_seen_at = now

    prior_success = await _latest_successful_extraction_for_artifact(session, artifact.id)
    if prior_success is None:
        extraction = await run_extraction(
            session,
            artifact,
            source,
            body=fetch.body,
            settings=cfg,
        )
        return await _apply_extraction_result(
            session,
            source,
            settings=cfg,
            result=result,
            extraction=extraction,
        )

    await _touch_source_health(
        session,
        source.id,
        success=True,
        message="fetch and extraction completed",
    )
    _schedule_next_fetch(source, settings=cfg, success=True, failures=0)
    await session.flush()
    return result
