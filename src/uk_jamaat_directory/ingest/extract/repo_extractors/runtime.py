from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import ExtractionKind, SourceType
from uk_jamaat_directory.ingest.artifacts import record_fetched_artifact
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractorArtifact,
    ExtractorRow,
    RunFrequency,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    RegisteredExtractor,
    load_all_extractors,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.runner import (
    SandboxRunResult,
    run_sandbox,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_extractor,
    check_extractor_result,
    check_target_url,
)
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.ingest.normalize import normalize_domain
from uk_jamaat_directory.models.core import (
    ExtractionRun,
    Mosque,
    MosqueSource,
    SourceArtifact,
    SourceExtractorAssignment,
)
from uk_jamaat_directory.schedules.candidates import upsert_schedule_candidate
from uk_jamaat_directory.schedules.publication import validate_candidates
from uk_jamaat_directory.schedules.types import ScheduleCandidateInput
from uk_jamaat_directory.storage.s3 import S3Storage

SCHEDULE_DELTAS: dict[RunFrequency, timedelta] = {
    RunFrequency.HOURLY: timedelta(hours=1),
    RunFrequency.DAILY: timedelta(days=1),
    RunFrequency.WEEKLY: timedelta(weeks=1),
    RunFrequency.MONTHLY: timedelta(days=30),
    RunFrequency.RAMADAN_DAILY: timedelta(days=1),
    RunFrequency.MANUAL: timedelta(days=365),
}

BACKOFF_HOURS: tuple[int, ...] = (2, 4, 8, 24)


@dataclass
class RepoExtractionOutcome:
    extractor_key: str
    extractor_version: str
    artifact_ids: list[uuid.UUID]
    rows: int
    status: str
    error: str | None
    warnings: list[str]
    duration_ms: int


async def latest_artifact_for_url(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    fetched_url: str,
) -> SourceArtifact | None:
    return await session.scalar(
        select(SourceArtifact)
        .where(SourceArtifact.source_id == source_id)
        .where(SourceArtifact.fetched_url == fetched_url)
        .order_by(SourceArtifact.fetched_at.desc())
        .limit(1)
    )


def _is_repo_extractor_due(
    assignment: SourceExtractorAssignment, *, now: datetime
) -> bool:
    if assignment.status != "active":
        return False
    if assignment.next_run_at is None:
        return True
    next_run = assignment.next_run_at
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=UTC)
    return next_run <= now


async def list_due_repo_extractor_source_ids(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> list[uuid.UUID]:
    cfg = settings or get_settings()
    if not cfg.crawl_enabled:
        return []
    now = datetime.now(UTC)
    stmt = (
        select(SourceExtractorAssignment.source_id)
        .join(MosqueSource, MosqueSource.id == SourceExtractorAssignment.source_id)
        .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
        .where(SourceExtractorAssignment.status == "active")
    )
    rows = (await session.execute(stmt)).scalars().all()
    due: list[uuid.UUID] = []
    for source_id in rows:
        source = await session.get(MosqueSource, source_id)
        if source is None:
            continue
        metadata = source.metadata_ or {}
        if metadata.get("crawl_enabled") is False:
            continue
        assignment = await session.get(SourceExtractorAssignment, source_id)
        if assignment is None:
            continue
        if _is_repo_extractor_due(assignment, now=now):
            due.append(source_id)
    return due


def _schedule_next_run(
    assignment: SourceExtractorAssignment, *, success: bool
) -> None:
    now = datetime.now(UTC)
    assignment.last_run_at = now
    if success:
        delta = SCHEDULE_DELTAS.get(
            RunFrequency(assignment.run_frequency), timedelta(days=1)
        )
        assignment.next_run_at = now + delta
        assignment.consecutive_failures = 0
    else:
        idx = min(assignment.consecutive_failures, len(BACKOFF_HOURS) - 1)
        hours = BACKOFF_HOURS[idx]
        assignment.next_run_at = now + timedelta(hours=hours)
        assignment.consecutive_failures += 1


async def _fetch_target_artifact(
    session: AsyncSession,
    source: MosqueSource,
    target: TargetSpec,
    *,
    settings: Settings,
) -> tuple[SourceArtifact, bytes] | str:
    parsed = urlparse(target.url)
    if not parsed.netloc:
        return f"target {target.label} has no host"
    prior = await latest_artifact_for_url(
        session, source_id=source.id, fetched_url=target.url
    )
    fetch = await fetch_url(target.url, prior_artifact=prior, settings=settings)
    if fetch.error:
        return f"target {target.label} fetch failed: {fetch.error}"
    if fetch.unchanged:
        if prior is None:
            return f"target {target.label} returned unchanged without prior artifact"
        prior.last_seen_at = datetime.now(UTC)
        body = b""
        if prior.object_key:
            storage = S3Storage(settings)
            body = await storage.get_bytes(prior.object_key)
        return prior, body
    content_type = fetch.content_type or "application/octet-stream"
    artifact, _created, _hash = await record_fetched_artifact(
        session,
        source,
        fetched_url=target.url,
        body=fetch.body or b"",
        content_type=content_type,
        etag=fetch.etag,
        last_modified=fetch.last_modified,
        upload_to_s3=True,
        settings=settings,
    )
    return artifact, fetch.body or b""


async def _build_sandbox_payload(
    *,
    extractor: RegisteredExtractor,
    source: MosqueSource,
    mosque: Mosque | None,
    artifacts: dict[str, ExtractorArtifact],
) -> dict:
    return {
        "extractor_key": extractor.extractor.key,
        "source_id": str(source.id),
        "mosque_name": mosque.name if mosque else "",
        "mosque_id": str(mosque.id) if mosque else None,
        "source_url": source.source_url or "",
        "timezone": (
            (source.metadata_ or {}).get("timezone", "Europe/London")
            if source.metadata_
            else "Europe/London"
        ),
        "artifacts": {
            label: {
                "target_label": artifact.target_label,
                "target_url": artifact.target_url,
                "content_type": artifact.content_type,
                "body_hex": artifact.body.hex(),
                "content_hash": artifact.content_hash,
            }
            for label, artifact in artifacts.items()
        },
    }


def _row_to_candidate_input(row: ExtractorRow) -> ScheduleCandidateInput:
    return ScheduleCandidateInput(
        date=row.date,
        prayer=row.prayer,
        session_number=row.session_number,
        session_label=row.session_label,
        timezone=row.timezone,
        start_time=row.start_time,
        jamaat_time=row.jamaat_time,
    )


async def run_extractor_for_source(
    session: AsyncSession,
    source: MosqueSource,
    *,
    settings: Settings | None = None,
) -> RepoExtractionOutcome:
    cfg = settings or get_settings()
    assignment = await session.get(SourceExtractorAssignment, source.id)
    if assignment is None or assignment.status != "active":
        return RepoExtractionOutcome(
            extractor_key="",
            extractor_version="",
            artifact_ids=[],
            rows=0,
            status="skipped",
            error="no active repo extractor assignment",
            warnings=[],
            duration_ms=0,
        )

    mosque = await session.get(Mosque, source.mosque_id) if source.mosque_id else None
    domain = normalize_domain(source.source_url)
    matches = [
        entry
        for entry in load_all_extractors()
        if entry.extractor.key == assignment.extractor_key
    ]
    if not matches:
        _record_failure(assignment, "assigned extractor not found in registry")
        return RepoExtractionOutcome(
            extractor_key=assignment.extractor_key,
            extractor_version=assignment.extractor_version,
            artifact_ids=[],
            rows=0,
            status="failed",
            error=f"assigned extractor not found: {assignment.extractor_key}",
            warnings=[],
            duration_ms=0,
        )
    registered = matches[0]

    capability_issues = check_extractor(registered.extractor, allowed_domain=domain)
    if capability_issues:
        _record_failure(assignment, "; ".join(capability_issues))
        return RepoExtractionOutcome(
            extractor_key=registered.extractor.key,
            extractor_version=registered.extractor.version,
            artifact_ids=[],
            rows=0,
            status="failed",
            error="; ".join(capability_issues),
            warnings=[],
            duration_ms=0,
        )

    artifacts: dict[str, ExtractorArtifact] = {}
    artifact_ids: list[uuid.UUID] = []
    for target in registered.extractor.targets:
        url_issue = check_target_url(target.url, allowed_domain=domain)
        if url_issue is not None:
            _record_failure(assignment, url_issue)
            return RepoExtractionOutcome(
                extractor_key=registered.extractor.key,
                extractor_version=registered.extractor.version,
                artifact_ids=artifact_ids,
                rows=0,
                status="failed",
                error=url_issue,
                warnings=[],
                duration_ms=0,
            )
        fetched = await _fetch_target_artifact(
            session, source, target, settings=cfg
        )
        if isinstance(fetched, str):
            _record_failure(assignment, fetched)
            return RepoExtractionOutcome(
                extractor_key=registered.extractor.key,
                extractor_version=registered.extractor.version,
                artifact_ids=artifact_ids,
                rows=0,
                status="failed",
                error=fetched,
                warnings=[],
                duration_ms=0,
            )
        artifact, body = fetched
        artifact_ids.append(artifact.id)
        artifacts[target.label] = ExtractorArtifact(
            target_label=target.label,
            target_url=target.url,
            content_type=artifact.content_type,
            body=body,
            content_hash=artifact.content_hash,
        )

    sandbox_payload = await _build_sandbox_payload(
        extractor=registered,
        source=source,
        mosque=mosque,
        artifacts=artifacts,
    )
    heavy = any(
        t.requires_pdf or t.requires_ocr or t.requires_javascript
        for t in registered.extractor.targets
    )
    sandbox_result: SandboxRunResult = await run_sandbox(
        registered.extractor.key,
        sandbox_payload,
        settings=cfg,
        heavy=heavy,
    )
    if not sandbox_result.ok or sandbox_result.result is None:
        _record_failure(assignment, sandbox_result.error or "sandbox failed")
        return RepoExtractionOutcome(
            extractor_key=registered.extractor.key,
            extractor_version=registered.extractor.version,
            artifact_ids=artifact_ids,
            rows=0,
            status="failed",
            error=sandbox_result.error or "sandbox failed",
            warnings=[],
            duration_ms=sandbox_result.duration_ms,
        )

    output_issues = check_extractor_result(sandbox_result.result)
    if output_issues:
        _record_failure(assignment, "; ".join(output_issues))
        return RepoExtractionOutcome(
            extractor_key=registered.extractor.key,
            extractor_version=registered.extractor.version,
            artifact_ids=artifact_ids,
            rows=0,
            status="failed",
            error="; ".join(output_issues),
            warnings=[w.message for w in sandbox_result.result.warnings],
            duration_ms=sandbox_result.duration_ms,
        )

    primary_artifact_id = artifact_ids[0] if artifact_ids else None
    extraction_run = ExtractionRun(
        id=uuid.uuid4(),
        artifact_id=primary_artifact_id,
        source_id=source.id,
        kind=ExtractionKind.DETERMINISTIC,
        extractor_version=(
            f"repo:{registered.extractor.key}@{registered.extractor.version}"
        ),
        status="succeeded" if sandbox_result.result.rows else "failed",
        score=None,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata_={
            "extractor_key": registered.extractor.key,
            "extractor_version": registered.extractor.version,
            "artifact_ids": [str(aid) for aid in artifact_ids],
            "target_urls": [t.url for t in registered.extractor.targets],
            "target_labels": [t.label for t in registered.extractor.targets],
            "contract": "repo_site_extractor/v1",
            "gate_passed": True,
            "warnings": [w.message for w in sandbox_result.result.warnings],
            "duration_ms": sandbox_result.duration_ms,
        },
    )
    session.add(extraction_run)
    await session.flush()

    created_rows = 0
    for row in sandbox_result.result.rows:
        if mosque is None:
            continue
        target_label = row.evidence.target_label
        artifact_id: str | None = None
        for idx, t in enumerate(registered.extractor.targets):
            if t.label == target_label and idx < len(artifact_ids):
                artifact_id = str(artifact_ids[idx])
                break
        evidence_extra = {
            "extractor_key": registered.extractor.key,
            "extractor_version": registered.extractor.version,
            "artifact_id": artifact_id or "",
            "contract": "repo_site_extractor/v1",
            "gate_passed": True,
        }
        if row.evidence.derivation is not None:
            evidence_extra["derivation"] = row.evidence.derivation
        await upsert_schedule_candidate(
            session,
            mosque=mosque,
            source=source,
            extraction_run_id=extraction_run.id,
            row=_row_to_candidate_input(row),
            jamaat_time=row.jamaat_time,
            start_time=row.start_time,
            evidence_extra=evidence_extra,
        )
        created_rows += 1

    if cfg.crawl_validate_after_extract:
        await validate_candidates(session, source_ids={source.id})

    _schedule_next_run(assignment, success=created_rows > 0)
    if created_rows > 0:
        assignment.last_success_at = datetime.now(UTC)
    else:
        assignment.last_failure_at = datetime.now(UTC)
        assignment.last_error = "extractor produced no schedule rows"

    await session.flush()
    return RepoExtractionOutcome(
        extractor_key=registered.extractor.key,
        extractor_version=registered.extractor.version,
        artifact_ids=artifact_ids,
        rows=created_rows,
        status="succeeded" if created_rows > 0 else "failed",
        error=None if created_rows > 0 else "extractor produced no schedule rows",
        warnings=[w.message for w in sandbox_result.result.warnings],
        duration_ms=sandbox_result.duration_ms,
    )


def _record_failure(assignment: SourceExtractorAssignment, error: str) -> None:
    assignment.consecutive_failures += 1
    assignment.last_failure_at = datetime.now(UTC)
    assignment.last_error = error
    assignment.last_run_at = datetime.now(UTC)
