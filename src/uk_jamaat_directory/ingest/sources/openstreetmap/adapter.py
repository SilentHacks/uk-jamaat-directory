from __future__ import annotations

import json
from pathlib import Path

from uk_jamaat_directory.domain import Confidence, SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.discovery.records import DiscoveryRecord
from uk_jamaat_directory.ingest.sources.openstreetmap.schema import OsmImportBundle, OsmPlaceRecord

MUSLIM_DENOMINATIONS = frozenset({"muslim", "sunni", "shia", "ahmadiyya"})


def validate_osm_bundle(bundle: OsmImportBundle) -> OsmImportBundle:
    places = [_place_from_dict(place.model_dump()) for place in bundle.places]
    return OsmImportBundle(
        format_version=bundle.format_version,
        exported_at=bundle.exported_at,
        attribution=bundle.attribution,
        places=places,
    )


def parse_osm_file(path: Path) -> OsmImportBundle:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "places" in payload:
        places = [_place_from_dict(item) for item in payload["places"]]
        return OsmImportBundle(
            format_version="1",
            exported_at=payload.get("exported_at"),
            attribution=str(payload.get("attribution", "© OpenStreetMap contributors (ODbL 1.0)")),
            places=places,
        )
    if "osm_type" in payload and "osm_id" in payload:
        return OsmImportBundle(places=[_place_from_dict(payload)])
    msg = "OSM JSON must contain 'places' or a single place record"
    raise ValueError(msg)


def _place_from_dict(data: dict[str, object]) -> OsmPlaceRecord:
    record = OsmPlaceRecord.model_validate(data)
    if not is_muslim_place(record):
        msg = f"record {record.external_id} is not a Muslim place of worship"
        raise ValueError(msg)
    return record


def is_muslim_place(record: OsmPlaceRecord) -> bool:
    religion = (record.religion or "").strip().lower()
    denomination = (record.denomination or "").strip().lower()
    if religion == "muslim":
        return True
    if denomination in MUSLIM_DENOMINATIONS:
        return True
    name_lower = record.name.lower()
    return any(token in name_lower for token in ("masjid", "mosque", "islamic"))


def osm_to_discovery_record(record: OsmPlaceRecord) -> DiscoveryRecord:
    return DiscoveryRecord(
        source_type=SourceType.OPENSTREETMAP,
        external_id=record.external_id,
        name=record.name,
        aliases=record.aliases,
        address_line1=record.address_line1,
        city=record.city,
        postcode=record.postcode,
        country=record.country,
        website_url=record.website_url,
        latitude=record.latitude,
        longitude=record.longitude,
        source_url=record.source_url
        or f"https://www.openstreetmap.org/{record.osm_type}/{record.osm_id}",
        attribution="© OpenStreetMap contributors (ODbL 1.0)",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata={
            "osm_type": record.osm_type,
            "osm_id": record.osm_id,
            "religion": record.religion,
            "denomination": record.denomination,
            "latitude": record.latitude,
            "longitude": record.longitude,
            "location_precision": "osm_geometry",
            "source_record_updated_at": record.source_record_updated_at.isoformat()
            if record.source_record_updated_at is not None
            else None,
            "osm_version": record.osm_version,
            "osm_changeset": record.osm_changeset,
            "osm_user": record.osm_user,
            "license": "ODbL-1.0",
            "website_tags": list(record.website_tags),
        },
    )
