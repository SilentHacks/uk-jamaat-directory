from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.ingest.discovery.records import (
    MatchDecision,
    ResolvedDiscovery,
    ResolveOutcome,
)
from uk_jamaat_directory.ingest.discovery.resolve import resolve_discovery_record
from uk_jamaat_directory.ingest.sources.openstreetmap.adapter import osm_to_discovery_record
from uk_jamaat_directory.ingest.sources.openstreetmap.schema import OsmImportBundle


@dataclass
class OsmImportResult:
    places_processed: int = 0
    mosques_created: int = 0
    mosques_linked: int = 0
    reviews_created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


async def import_openstreetmap_bundle(
    session: AsyncSession,
    bundle: OsmImportBundle,
) -> OsmImportResult:
    result = OsmImportResult()
    for place in bundle.places:
        try:
            async with session.begin_nested():
                discovery = osm_to_discovery_record(place)
                if bundle.exported_at is not None:
                    discovery.metadata["source_exported_at"] = bundle.exported_at.isoformat()
                resolved = await resolve_discovery_record(session, discovery)
                _record_result(result, resolved)
        except (ValueError, SQLAlchemyError) as exc:
            result.errors.append(f"{place.external_id}: {exc}")
            result.skipped += 1

    return result


def _record_result(result: OsmImportResult, resolved: ResolvedDiscovery) -> None:
    result.places_processed += 1
    if resolved.match.decision == MatchDecision.NEEDS_REVIEW:
        result.reviews_created += 1
    elif resolved.outcome == ResolveOutcome.AUTO_LINK_MATCH:
        result.mosques_linked += 1
    if resolved.outcome == ResolveOutcome.CREATED_NEEDS_REVIEW:
        result.mosques_created += 1
