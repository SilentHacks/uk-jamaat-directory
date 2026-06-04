from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geoalchemy2 import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    SourceType,
)
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.ingest.policy import parse_publication_policy
from uk_jamaat_directory.models.core import ModerationAction, Mosque, MosqueAlias, MosqueSource
from uk_jamaat_directory.schemas.admin import (
    AdminAliasCreate,
    AdminMosqueCreate,
    AdminMosqueMerge,
    AdminMosqueUpdate,
    AdminSourceAttach,
)


async def create_mosque(
    session: AsyncSession,
    payload: AdminMosqueCreate,
    *,
    actor: str,
) -> Mosque:
    mosque = Mosque(
        id=uuid.uuid4(),
        name=payload.name,
        normalized_name=normalize_mosque_name(payload.name),
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        county=payload.county,
        postcode=payload.postcode,
        country=payload.country,
        website_url=payload.website_url,
        status=MosqueStatus(payload.status),
        public_notes=payload.public_notes,
    )
    if payload.latitude is not None and payload.longitude is not None:
        mosque.location = WKTElement(
            f"POINT({payload.longitude} {payload.latitude})",
            srid=4326,
        )
    session.add(mosque)
    await _audit(
        session,
        actor=actor,
        action="create_mosque",
        entity_type="mosque",
        entity_id=mosque.id,
    )
    await session.flush()
    return mosque


async def update_mosque(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    payload: AdminMosqueUpdate,
    *,
    actor: str,
) -> Mosque:
    mosque = await session.get_one(Mosque, mosque_id)
    if payload.name is not None:
        mosque.name = payload.name
        mosque.normalized_name = normalize_mosque_name(payload.name)
    for field in (
        "address_line1",
        "address_line2",
        "city",
        "county",
        "postcode",
        "country",
        "website_url",
        "public_notes",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(mosque, field, value)
    if payload.status is not None:
        mosque.status = MosqueStatus(payload.status)
    if payload.latitude is not None and payload.longitude is not None:
        mosque.location = WKTElement(
            f"POINT({payload.longitude} {payload.latitude})",
            srid=4326,
        )
    await _audit(
        session,
        actor=actor,
        action="update_mosque",
        entity_type="mosque",
        entity_id=mosque.id,
    )
    await session.flush()
    return mosque


async def attach_source(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    payload: AdminSourceAttach,
    *,
    actor: str,
) -> MosqueSource:
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        source_type=SourceType(payload.source_type),
        external_id=payload.external_id,
        source_url=payload.source_url,
        display_name=payload.display_name,
        publication_policy=parse_publication_policy(payload.publication_policy),
        confidence=Confidence(payload.confidence),
        attribution=payload.attribution,
        last_seen_at=datetime.now(UTC),
    )
    session.add(source)
    await _audit(
        session,
        actor=actor,
        action="attach_source",
        entity_type="mosque_source",
        entity_id=source.id,
        metadata={"mosque_id": str(mosque_id)},
    )
    await session.flush()
    return source


async def add_alias(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    payload: AdminAliasCreate,
    *,
    actor: str,
) -> MosqueAlias:
    alias = MosqueAlias(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        alias=payload.alias,
        normalized_alias=normalize_mosque_name(payload.alias),
        source_type=SourceType.MANUAL,
    )
    session.add(alias)
    await _audit(
        session,
        actor=actor,
        action="add_alias",
        entity_type="mosque_alias",
        entity_id=alias.id,
        metadata={"mosque_id": str(mosque_id)},
    )
    await session.flush()
    return alias


async def merge_mosques(
    session: AsyncSession,
    canonical_mosque_id: uuid.UUID,
    payload: AdminMosqueMerge,
    *,
    actor: str,
) -> Mosque:
    canonical = await session.get_one(Mosque, canonical_mosque_id)
    duplicate = await session.get_one(Mosque, payload.duplicate_mosque_id)
    if duplicate.id == canonical.id:
        msg = "cannot merge a mosque into itself"
        raise ValueError(msg)

    sources = (
        await session.scalars(select(MosqueSource).where(MosqueSource.mosque_id == duplicate.id))
    ).all()
    for source in sources:
        source.mosque_id = canonical.id

    duplicate.status = MosqueStatus.DUPLICATE
    await _audit(
        session,
        actor=actor,
        action="merge_mosque",
        entity_type="mosque",
        entity_id=canonical.id,
        reason=payload.reason,
        metadata={"duplicate_mosque_id": str(duplicate.id)},
    )
    await session.flush()
    return canonical


async def record_discovery_lead(
    session: AsyncSession,
    *,
    query: str,
    notes: str | None,
    location_hint: str | None,
    actor: str,
) -> uuid.UUID:
    lead_id = uuid.uuid4()
    action = ModerationAction(
        id=uuid.uuid4(),
        actor=actor,
        action="google_discovery_lead",
        entity_type="discovery_lead",
        entity_id=lead_id,
        reason=notes,
        metadata_={
            "query": query,
            "location_hint": location_hint,
            "provider": "google",
            "policy": "admin_only_private",
        },
    )
    session.add(action)
    await session.flush()
    return lead_id


async def _audit(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    reason: str | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    session.add(
        ModerationAction(
            id=uuid.uuid4(),
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            reason=reason,
            metadata_=metadata or {},
        )
    )
