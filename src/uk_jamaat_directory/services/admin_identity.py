from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    SourceType,
)
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.resolve import _ensure_alias
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.ingest.policy import parse_publication_policy
from uk_jamaat_directory.models.core import (
    Correction,
    IdentityMatchReview,
    ModerationAction,
    Mosque,
    MosqueAlias,
    MosqueAttribute,
    MosqueClaim,
    MosqueSource,
    ScheduleCandidate,
    ScheduleOccurrence,
)
from uk_jamaat_directory.schemas.admin import (
    AdminAliasCreate,
    AdminMosqueCreate,
    AdminMosqueMerge,
    AdminMosqueUpdate,
    AdminSourceAttach,
)
from uk_jamaat_directory.services.errors import DuplicateAliasError, MosqueNotFoundError


async def _require_mosque(session: AsyncSession, mosque_id: uuid.UUID) -> Mosque:
    mosque = await session.get(Mosque, mosque_id)
    if mosque is None:
        raise MosqueNotFoundError(str(mosque_id))
    return mosque


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
    set_mosque_point(mosque, payload.latitude, payload.longitude)
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
    mosque = await _require_mosque(session, mosque_id)
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
        set_mosque_point(mosque, payload.latitude, payload.longitude)
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
    await _require_mosque(session, mosque_id)
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
    await _require_mosque(session, mosque_id)
    alias = MosqueAlias(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        alias=payload.alias,
        normalized_alias=normalize_mosque_name(payload.alias),
        source_type=SourceType.MANUAL,
    )
    session.add(alias)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateAliasError("alias already exists for this mosque") from exc
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
    canonical = await _require_mosque(session, canonical_mosque_id)
    duplicate = await _require_mosque(session, payload.duplicate_mosque_id)
    if duplicate.id == canonical.id:
        msg = "cannot merge a mosque into itself"
        raise ValueError(msg)

    for source in (
        await session.scalars(select(MosqueSource).where(MosqueSource.mosque_id == duplicate.id))
    ).all():
        source.mosque_id = canonical.id

    for alias in (
        await session.scalars(select(MosqueAlias).where(MosqueAlias.mosque_id == duplicate.id))
    ).all():
        conflict = await session.scalar(
            select(MosqueAlias).where(
                MosqueAlias.mosque_id == canonical.id,
                MosqueAlias.normalized_alias == alias.normalized_alias,
            )
        )
        if conflict is not None:
            await session.delete(alias)
        else:
            alias.mosque_id = canonical.id

    for candidate in (
        await session.scalars(
            select(ScheduleCandidate).where(ScheduleCandidate.mosque_id == duplicate.id)
        )
    ).all():
        candidate.mosque_id = canonical.id

    for occurrence in (
        await session.scalars(
            select(ScheduleOccurrence).where(ScheduleOccurrence.mosque_id == duplicate.id)
        )
    ).all():
        occurrence.mosque_id = canonical.id

    for claim in (
        await session.scalars(select(MosqueClaim).where(MosqueClaim.mosque_id == duplicate.id))
    ).all():
        claim.mosque_id = canonical.id

    await session.execute(
        update(Correction)
        .where(Correction.mosque_id == duplicate.id)
        .values(mosque_id=canonical.id)
    )
    await session.execute(
        update(IdentityMatchReview)
        .where(IdentityMatchReview.proposed_mosque_id == duplicate.id)
        .values(proposed_mosque_id=canonical.id)
    )

    dup_attr = await session.get(MosqueAttribute, duplicate.id)
    if dup_attr is not None:
        canonical_attr = await session.get(MosqueAttribute, canonical.id)
        if canonical_attr is None:
            session.add(
                MosqueAttribute(
                    mosque_id=canonical.id,
                    facilities=dup_attr.facilities,
                    madhab=dup_attr.madhab,
                    affiliation=dup_attr.affiliation,
                    women_space=dup_attr.women_space,
                    parking=dup_attr.parking,
                    accessibility=dup_attr.accessibility,
                )
            )
        await session.delete(dup_attr)

    await _ensure_alias(session, canonical.id, duplicate.name, SourceType.MANUAL)

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
    await _audit(
        session,
        actor=actor,
        action="google_discovery_lead",
        entity_type="discovery_lead",
        entity_id=lead_id,
        reason=notes,
        metadata={
            "query": query,
            "location_hint": location_hint,
            "provider": "google",
            "policy": "admin_only_private",
        },
    )
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
    metadata: dict[str, Any] | None = None,
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
