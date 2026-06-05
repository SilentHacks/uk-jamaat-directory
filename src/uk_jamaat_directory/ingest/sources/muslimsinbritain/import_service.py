from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourcePublicationPolicy
from uk_jamaat_directory.ingest.discovery.records import (
    MatchDecision,
    ResolvedDiscovery,
    ResolveOutcome,
)
from uk_jamaat_directory.ingest.discovery.resolve import resolve_discovery_record
from uk_jamaat_directory.ingest.sources.muslimsinbritain.discovery import (
    mib_record_to_discovery,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import MibImportBundle


@dataclass
class MibImportResult:
    records_processed: int = 0
    mosques_created: int = 0
    mosques_linked: int = 0
    reviews_created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def import_muslimsinbritain_bundle(
    session: AsyncSession,
    bundle: MibImportBundle,
    *,
    publication_policy: SourcePublicationPolicy,
) -> MibImportResult:
    result = MibImportResult()
    for record in bundle.mosques:
        try:
            async with session.begin_nested():
                discovery = mib_record_to_discovery(
                    record,
                    publication_policy=publication_policy,
                )
                resolved = await resolve_discovery_record(session, discovery)
                _record_result(result, resolved)
        except (ValueError, SQLAlchemyError) as exc:
            result.errors.append(f"{record.external_id}: {exc}")
            result.skipped += 1

    return result


def _record_result(result: MibImportResult, resolved: ResolvedDiscovery) -> None:
    result.records_processed += 1
    if resolved.match.decision == MatchDecision.NEEDS_REVIEW:
        result.reviews_created += 1
    elif resolved.outcome == ResolveOutcome.AUTO_LINK_MATCH:
        result.mosques_linked += 1
    if resolved.outcome == ResolveOutcome.CREATED_NEEDS_REVIEW:
        result.mosques_created += 1
