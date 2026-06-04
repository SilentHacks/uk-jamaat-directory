from __future__ import annotations

from uk_jamaat_directory.domain import Confidence, SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.discovery.records import DiscoveryRecord
from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import MyLocalMasjidMosqueRecord

DEFAULT_ATTRIBUTION = "MyLocalMasjid"


def mlm_record_to_discovery(
    record: MyLocalMasjidMosqueRecord,
    *,
    publication_policy: SourcePublicationPolicy,
) -> DiscoveryRecord:
    return DiscoveryRecord(
        source_type=SourceType.MYLOCALMASJID,
        external_id=record.external_id,
        name=record.name,
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
        confidence=Confidence.PARTNER_IMPORT,
        metadata={
            "linkback_url": record.linkback_url,
            "profile_url": record.profile_url,
            "import_format_version": "1",
        },
    )
