from __future__ import annotations

from sqlalchemy import Row

from uk_jamaat_directory.models.core import (
    ChangeEvent,
    DatasetVersion,
    Mosque,
    MosqueAlias,
    MosqueAttribute,
    MosqueSource,
    ScheduleOccurrence,
)
from uk_jamaat_directory.schemas.public import (
    ChangeEventPublic,
    MosqueDetailPublic,
    MosqueSummaryPublic,
    PublicScheduleOccurrence,
    PublicSourceProvenance,
    SnapshotFormatInfo,
    SnapshotResponse,
)
from uk_jamaat_directory.services.public_policy import is_public_source_policy


def coordinates_from_location(location: object | None) -> tuple[float | None, float | None]:
    if location is None:
        return None, None
    # GeoAlchemy2 returns WKBElement; tests may pass through ORM-loaded values.
    try:
        from geoalchemy2.shape import to_shape

        point = to_shape(location)
        return float(point.y), float(point.x)
    except Exception:
        return None, None


def mosque_summary(
    mosque: Mosque,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    distance_metres: float | None = None,
) -> MosqueSummaryPublic:
    lat, lng = latitude, longitude
    if lat is None and lng is None:
        lat, lng = coordinates_from_location(mosque.location)

    return MosqueSummaryPublic(
        directory_mosque_id=mosque.id,
        name=mosque.name,
        city=mosque.city,
        postcode=mosque.postcode,
        latitude=lat,
        longitude=lng,
        status=mosque.status.value if hasattr(mosque.status, "value") else str(mosque.status),
        distance_metres=distance_metres,
    )


def mosque_detail(
    mosque: Mosque,
    *,
    aliases: list[MosqueAlias] | None = None,
    sources: list[MosqueSource] | None = None,
    attributes: MosqueAttribute | None = None,
) -> MosqueDetailPublic:
    lat, lng = coordinates_from_location(mosque.location)
    public_sources = [
        public_source_provenance(source)
        for source in (sources or [])
        if is_public_source_policy(source.publication_policy)
    ]

    facilities: dict[str, bool] = {}
    if attributes and attributes.facilities:
        facilities = {
            key: bool(value)
            for key, value in attributes.facilities.items()
            if isinstance(value, bool)
        }

    return MosqueDetailPublic(
        directory_mosque_id=mosque.id,
        name=mosque.name,
        address_line1=mosque.address_line1,
        address_line2=mosque.address_line2,
        city=mosque.city,
        county=mosque.county,
        postcode=mosque.postcode,
        country=mosque.country,
        website_url=mosque.website_url,
        latitude=lat,
        longitude=lng,
        status=mosque.status.value if hasattr(mosque.status, "value") else str(mosque.status),
        aliases=[alias.alias for alias in (aliases or [])],
        sources=public_sources,
        facilities=facilities,
    )


def public_source_provenance(source: MosqueSource) -> PublicSourceProvenance:
    return PublicSourceProvenance(
        source_type=source.source_type.value
        if hasattr(source.source_type, "value")
        else str(source.source_type),
        source_url=source.source_url,
        confidence=source.confidence.value
        if hasattr(source.confidence, "value")
        else str(source.confidence),
        attribution=source.attribution,
        last_seen_at=source.last_seen_at,
    )


def schedule_occurrence(
    occurrence: ScheduleOccurrence,
    *,
    source: MosqueSource,
    dataset_version: str | None = None,
) -> PublicScheduleOccurrence:
    return PublicScheduleOccurrence(
        directory_mosque_id=occurrence.mosque_id,
        date=occurrence.date,
        prayer=occurrence.prayer.value
        if hasattr(occurrence.prayer, "value")
        else str(occurrence.prayer),
        start_time=occurrence.start_time,
        jamaat_time=occurrence.jamaat_time,
        session_number=occurrence.session_number,
        session_label=occurrence.session_label,
        timezone=occurrence.timezone,
        confidence=occurrence.confidence.value
        if hasattr(occurrence.confidence, "value")
        else str(occurrence.confidence),
        source_type=source.source_type.value
        if hasattr(source.source_type, "value")
        else str(source.source_type),
        source_url=occurrence.source_url or source.source_url,
        last_verified_at=occurrence.last_verified_at,
        freshness_status=occurrence.freshness_status.value
        if hasattr(occurrence.freshness_status, "value")
        else str(occurrence.freshness_status),
        dataset_version=dataset_version,
    )


def schedule_occurrence_from_row(row: Row[tuple]) -> PublicScheduleOccurrence:
    occurrence: ScheduleOccurrence = row[0]
    source: MosqueSource = row[1]
    dataset_version: DatasetVersion | None = row[2] if len(row) > 2 else None
    return schedule_occurrence(
        occurrence,
        source=source,
        dataset_version=dataset_version.version if dataset_version else None,
    )


def change_event_public(
    event: ChangeEvent, *, dataset_version: str | None = None
) -> ChangeEventPublic:
    return ChangeEventPublic(
        id=event.id,
        event_type=event.event_type.value
        if hasattr(event.event_type, "value")
        else str(event.event_type),
        occurred_at=event.created_at,
        directory_mosque_id=event.mosque_id,
        occurrence_id=event.occurrence_id,
        dataset_version=dataset_version,
        payload=event.payload or {},
    )


def snapshot_response(
    version: DatasetVersion, *, format_name: str | None = None
) -> SnapshotResponse:
    exports = (version.manifest or {}).get("exports", {})
    formats: list[SnapshotFormatInfo] = []

    if format_name:
        export_info = exports.get(format_name)
        if export_info:
            formats.append(
                SnapshotFormatInfo(
                    format=format_name,
                    url=export_info.get("url"),
                    checksum=export_info.get("checksum"),
                    size_bytes=export_info.get("size_bytes"),
                )
            )
    else:
        for name, export_info in exports.items():
            formats.append(
                SnapshotFormatInfo(
                    format=name,
                    url=export_info.get("url"),
                    checksum=export_info.get("checksum"),
                    size_bytes=export_info.get("size_bytes"),
                )
            )

    attribution = (version.manifest or {}).get("attribution", [])
    if not isinstance(attribution, list):
        attribution = []

    return SnapshotResponse(
        version=version.version,
        schema_version=version.schema_version,
        published_at=version.published_at,
        checksum=version.checksum,
        attribution=[str(item) for item in attribution],
        formats=formats,
    )
