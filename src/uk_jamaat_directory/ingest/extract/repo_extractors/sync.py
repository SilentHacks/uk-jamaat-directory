from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RunFrequency,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    find_extractor_for_source,
    load_all_extractors,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_extractor,
    validate_refresh_policy,
    validate_source_match,
)
from uk_jamaat_directory.ingest.normalize import normalize_domain
from uk_jamaat_directory.models.core import (
    Mosque,
    MosqueSource,
    SourceExtractorAssignment,
)

_DEFAULT_NEXT_RUN_BY_FREQUENCY: dict[RunFrequency, timedelta] = {
    RunFrequency.HOURLY: timedelta(hours=1),
    RunFrequency.DAILY: timedelta(hours=12),
    RunFrequency.WEEKLY: timedelta(days=1),
    RunFrequency.MONTHLY: timedelta(days=1),
    RunFrequency.RAMADAN_DAILY: timedelta(hours=12),
    RunFrequency.MANUAL: timedelta(days=365),
}


@dataclass
class SyncResult:
    upserted: list[str] = field(default_factory=list)
    matched_zero: list[str] = field(default_factory=list)
    matched_multiple: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[dict[str, Any]] = field(default_factory=list)
    marked_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


async def _mosque_name_for_source(
    session: AsyncSession, source: MosqueSource
) -> str | None:
    if source.mosque_id is None:
        return None
    mosque = await session.get(Mosque, source.mosque_id)
    return mosque.name if mosque else None


async def sync_repo_extractors(
    session: AsyncSession,
    *,
    source_id: uuid.UUID | None = None,
    extractor_key: str | None = None,
) -> SyncResult:
    result = SyncResult()
    extractors = {entry.extractor.key: entry for entry in load_all_extractors()}

    stmt = select(MosqueSource).where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
    if source_id is not None:
        stmt = stmt.where(MosqueSource.id == source_id)
    sources = (await session.execute(stmt)).scalars().all()

    for source in sources:
        domain = normalize_domain(source.source_url)
        if extractor_key is not None:
            match_keys = [extractor_key] if extractor_key in extractors else []
        else:
            match_keys = [
                m.extractor.key
                for m in find_extractor_for_source(
                    domain=domain,
                    mosque_name=await _mosque_name_for_source(session, source),
                )
            ]
        if not match_keys:
            result.matched_zero.append(str(source.id))
            continue
        if len(match_keys) > 1:
            result.matched_multiple.append(
                {"source_id": str(source.id), "extractor_keys": match_keys}
            )
            continue
        key = match_keys[0]
        entry = extractors[key]
        issues = list(validate_source_match(entry.extractor.source_match)) + list(
            validate_refresh_policy(entry.extractor.refresh_policy)
        )
        issues.extend(check_extractor(entry.extractor, allowed_domain=domain))
        if issues:
            result.invalid.append(
                {
                    "source_id": str(source.id),
                    "extractor_key": key,
                    "issues": list(issues),
                }
            )
            continue

        assignment = await session.get(SourceExtractorAssignment, source.id)
        frequency = entry.extractor.refresh_policy.frequency.value
        if assignment is None:
            assignment = SourceExtractorAssignment(
                source_id=source.id,
                extractor_key=key,
                extractor_version=entry.extractor.version,
                status="active",
                run_frequency=frequency,
                run_timezone=entry.extractor.refresh_policy.timezone,
                next_run_at=datetime.now(UTC)
                + _DEFAULT_NEXT_RUN_BY_FREQUENCY.get(
                    entry.extractor.refresh_policy.frequency,
                    timedelta(hours=12),
                ),
            )
            session.add(assignment)
        else:
            assignment.extractor_key = key
            assignment.extractor_version = entry.extractor.version
            assignment.run_frequency = frequency
            assignment.run_timezone = entry.extractor.refresh_policy.timezone
            if assignment.status == "failed_validation":
                assignment.status = "active"
        result.upserted.append(f"{source.id}={key}")

    if not extractor_key:
        known_keys = set(extractors.keys())
        assignment_stmt = select(SourceExtractorAssignment)
        if source_id is not None:
            assignment_stmt = assignment_stmt.where(
                SourceExtractorAssignment.source_id == source_id
            )
        assignments = (await session.execute(assignment_stmt)).scalars().all()
        for assignment in assignments:
            if assignment.extractor_key not in known_keys:
                assignment.status = "missing_script"
                result.marked_missing.append(str(assignment.source_id))

    await session.flush()
    return result
