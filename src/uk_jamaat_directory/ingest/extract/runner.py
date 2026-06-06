from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import ExtractionKind
from uk_jamaat_directory.ingest.extract.types import ExtractResult
from uk_jamaat_directory.models.core import ExtractionRun, Mosque, MosqueSource, SourceArtifact
from uk_jamaat_directory.schedules.candidates import upsert_schedule_candidate
from uk_jamaat_directory.schedules.publication import validate_candidates
from uk_jamaat_directory.schedules.types import ScheduleCandidateInput
from uk_jamaat_directory.storage.s3 import S3Storage


@dataclass
class ExtractionRunResult:
    extraction_run_id: uuid.UUID | None = None
    candidates_created: int = 0
    candidates_skipped: int = 0
    status: str = "skipped"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _route_extraction(
    *,
    body: bytes,  # noqa: ARG001
    content_type: str | None,  # noqa: ARG001
    source: MosqueSource,
) -> ExtractResult:
    return ExtractResult(
        warnings=[f"no extractor for source_type={source.source_type.value}"],
    )


async def run_extraction(
    session: AsyncSession,
    artifact: SourceArtifact,
    source: MosqueSource,
    *,
    mosque: Mosque | None = None,
    body: bytes | None = None,
    settings: Settings | None = None,
) -> ExtractionRunResult:
    cfg = settings or get_settings()
    result = ExtractionRunResult()

    if mosque is None and source.mosque_id is not None:
        mosque = await session.get(Mosque, source.mosque_id)
    if mosque is None:
        result.errors.append("source is not linked to a mosque")
        result.status = "failed"
        return result

    if body is None:
        if not artifact.object_key:
            result.errors.append("artifact has no object_key and no inline body")
            result.status = "failed"
            return result
        storage = S3Storage(cfg)
        body = await storage.get_bytes(artifact.object_key)

    extract_result = _route_extraction(
        body=body,
        content_type=artifact.content_type,
        source=source,
    )
    result.warnings.extend(extract_result.warnings)

    started_at = datetime.now(UTC)
    run_status = "succeeded" if extract_result.rows else "failed"
    if extract_result.warnings and not extract_result.rows:
        run_status = "failed"

    extraction_run = ExtractionRun(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        source_id=source.id,
        kind=ExtractionKind.DETERMINISTIC,
        extractor_version=extract_result.extractor_version or "unknown",
        status=run_status,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        metadata_={
            "artifact_id": str(artifact.id),
            "warnings": extract_result.warnings[:20],
        },
    )
    session.add(extraction_run)
    await session.flush()
    result.extraction_run_id = extraction_run.id
    result.status = run_status

    if not extract_result.rows:
        if not result.errors:
            result.errors.append("extractor produced no schedule rows")
        return result

    evidence_extra = {
        "artifact_id": str(artifact.id),
        "extractor_version": extract_result.extractor_version,
    }
    for row in extract_result.rows:
        candidate_input = ScheduleCandidateInput(
            date=row.date,
            prayer=row.prayer,
            session_number=row.session_number,
            session_label=row.session_label,
            timezone=row.timezone,
        )
        updated, unchanged = await upsert_schedule_candidate(
            session,
            mosque=mosque,
            source=source,
            extraction_run_id=extraction_run.id,
            row=candidate_input,
            jamaat_time=row.jamaat_time,
            start_time=row.start_time,
            evidence_extra=evidence_extra,
        )
        if unchanged:
            result.candidates_skipped += 1
        else:
            result.candidates_created += 1

    if cfg.crawl_validate_after_extract:
        await validate_candidates(session, source_ids={source.id})

    await session.flush()
    return result
