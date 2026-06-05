from __future__ import annotations

from uk_jamaat_directory.domain import Confidence, SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.discovery.records import DiscoveryRecord
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import MibMosqueRecord

DEFAULT_ATTRIBUTION = "MuslimsInBritain.org"


def mib_record_to_discovery(
    record: MibMosqueRecord,
    *,
    publication_policy: SourcePublicationPolicy,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id=record.external_id,
        name=record.name,
        aliases=record.aliases,
        address_line1=record.address_line1,
        address_line2=record.address_line2,
        city=record.city,
        county=record.county,
        postcode=record.postcode,
        country=record.country,
        website_url=record.website_url,
        latitude=record.latitude,
        longitude=record.longitude,
        source_url=record.source_url,
        attribution=record.attribution or DEFAULT_ATTRIBUTION,
        publication_policy=publication_policy,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata={
            "country": record.country,
            "record_class": record.record_class,
            "usage": record.usage,
            "capacity": record.capacity,
            "women_facilities": record.women_facilities,
            "latitude": record.latitude,
            "longitude": record.longitude,
            "location_precision": record.location_precision,
            "metadata_confidence": record.metadata_confidence,
            "theme": record.theme,
            "management": record.management,
            "phone": record.phone,
            "license_note": (
                "MiB states material is drawn from the public domain; policy remains explicit."
            ),
        },
    )
