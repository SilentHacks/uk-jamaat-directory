from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import Confidence, SourcePublicationPolicy, SourceType
from uk_jamaat_directory.ingest.discovery.records import DiscoveryRecord
from uk_jamaat_directory.ingest.discovery.resolve import resolve_discovery_record
from uk_jamaat_directory.schemas.contributions import CommunityMosqueSubmission


async def submit_community_mosque(
    session: AsyncSession,
    payload: CommunityMosqueSubmission,
) -> tuple[str, str]:
    submission_id = str(uuid.uuid4())
    record = DiscoveryRecord(
        source_type=SourceType.COMMUNITY,
        external_id=submission_id,
        name=payload.name,
        address_line1=payload.address_line1,
        city=payload.city,
        postcode=payload.postcode,
        website_url=payload.website_url,
        latitude=payload.latitude,
        longitude=payload.longitude,
        publication_policy=SourcePublicationPolicy.UNKNOWN,
        confidence=Confidence.COMMUNITY,
        metadata={
            "message": payload.message,
            "submitter_name": payload.submitter_name,
            "submitter_email": payload.submitter_email,
            "private_contact": True,
        },
    )
    mosque, _source, _match = await resolve_discovery_record(session, record)
    status = "needs_review" if mosque is not None else "pending_identity_review"
    return submission_id, status
