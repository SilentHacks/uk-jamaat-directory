from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.ingest.discovery.records import MatchDecision
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
            discovery = osm_to_discovery_record(place)
            mosque, _source, match = await resolve_discovery_record(session, discovery)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{place.external_id}: {exc}")
            result.skipped += 1
            continue

        result.places_processed += 1
        if match.decision == MatchDecision.NEEDS_REVIEW:
            result.reviews_created += 1
        elif match.decision == MatchDecision.AUTO_LINK and match.reasons != [
            "existing_source_link"
        ]:
            result.mosques_linked += 1
        if mosque is not None and match.decision == MatchDecision.CREATE_NEEDS_REVIEW:
            result.mosques_created += 1
        elif mosque is not None:
            result.mosques_created += 1

    return result
