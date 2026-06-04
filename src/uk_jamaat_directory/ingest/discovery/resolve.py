from __future__ import annotations

import uuid
from datetime import UTC, datetime

from geoalchemy2 import WKTElement
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uk_jamaat_directory.domain import MosqueStatus, SourceType
from uk_jamaat_directory.ingest.discovery.matching import decide_match, score_mosque_candidate
from uk_jamaat_directory.ingest.discovery.records import (
    DiscoveryMatch,
    DiscoveryRecord,
    MatchDecision,
)
from uk_jamaat_directory.ingest.normalize import normalize_mosque_name
from uk_jamaat_directory.models.core import (
    IdentityMatchReview,
    Mosque,
    MosqueAlias,
    MosqueSource,
)
from uk_jamaat_directory.services.public_policy import is_public_source_policy


async def resolve_discovery_record(
    session: AsyncSession,
    record: DiscoveryRecord,
) -> tuple[Mosque | None, MosqueSource, DiscoveryMatch]:
    """Link a discovery record to an existing mosque or create a reviewable mosque."""
    source = await _get_source(session, record.source_type, record.external_id)
    if source is not None and source.mosque_id is not None:
        mosque = await session.get_one(Mosque, source.mosque_id)
        _update_source(source, record)
        if is_public_source_policy(record.publication_policy):
            _apply_mosque_fields(mosque, record)
        await session.flush()
        return (
            mosque,
            source,
            DiscoveryMatch(
                decision=MatchDecision.AUTO_LINK,
                mosque_id=mosque.id,
                reasons=["existing_source_link"],
            ),
        )

    if source is not None:
        _update_source(source, record)

    candidates = await _score_candidates(session, record)
    match = decide_match(record, candidates)

    if match.decision == MatchDecision.BLOCKED:
        if source is None:
            source = _new_source(record)
            session.add(source)
            await session.flush()
        return None, source, match

    mosque: Mosque | None = None
    if match.decision == MatchDecision.AUTO_LINK and match.mosque_id is not None:
        mosque = await session.get_one(Mosque, match.mosque_id)
    elif match.decision == MatchDecision.CREATE_NEEDS_REVIEW:
        mosque = _new_mosque(record)
        session.add(mosque)
        await session.flush()
    elif match.decision == MatchDecision.NEEDS_REVIEW:
        if source is None:
            source = _new_source(record, mosque_id=None)
            session.add(source)
            await session.flush()
        else:
            _update_source(source, record)
        await _create_match_review(session, record, match, source_id=source.id)
        return None, source, match

    if mosque is None:
        mosque = _new_mosque(record)
        session.add(mosque)
        await session.flush()

    if source is None:
        source = _new_source(record, mosque_id=mosque.id)
        session.add(source)
    else:
        source.mosque_id = mosque.id
        _update_source(source, record)

    if is_public_source_policy(record.publication_policy):
        _apply_mosque_fields(mosque, record)

    for alias in record.aliases:
        await _ensure_alias(session, mosque.id, alias, record.source_type)

    await session.flush()
    return mosque, source, match


async def _score_candidates(
    session: AsyncSession,
    record: DiscoveryRecord,
) -> list:
    stmt = select(Mosque).options(selectinload(Mosque.aliases))
    if record.postcode:
        from uk_jamaat_directory.ingest.normalize import normalize_postcode

        normalized = normalize_postcode(record.postcode)
        if normalized:
            stmt = stmt.where(Mosque.postcode.is_not(None))
    mosques = (await session.scalars(stmt.limit(500))).all()

    scored = []
    for mosque in mosques:
        if record.postcode:
            from uk_jamaat_directory.ingest.normalize import normalize_postcode

            if normalize_postcode(mosque.postcode) != normalize_postcode(record.postcode):
                if record.city and mosque.city:
                    from uk_jamaat_directory.ingest.normalize import normalize_city

                    if normalize_city(record.city) != normalize_city(mosque.city):
                        continue
        candidate = score_mosque_candidate(record, mosque, aliases=mosque.aliases)
        if candidate is not None:
            scored.append(candidate)
    return scored


async def _get_source(
    session: AsyncSession,
    source_type: SourceType,
    external_id: str,
) -> MosqueSource | None:
    return await session.scalar(
        select(MosqueSource).where(
            MosqueSource.source_type == source_type,
            MosqueSource.external_id == external_id,
        )
    )


def _new_source(record: DiscoveryRecord, *, mosque_id: uuid.UUID | None) -> MosqueSource:
    return MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque_id,
        source_type=record.source_type,
        external_id=record.external_id,
        source_url=record.source_url,
        display_name=record.display_name,
        publication_policy=record.publication_policy,
        confidence=record.confidence,
        attribution=record.attribution,
        last_seen_at=datetime.now(UTC),
        metadata_=dict(record.metadata),
    )


def _update_source(source: MosqueSource, record: DiscoveryRecord) -> None:
    source.source_url = record.source_url
    source.display_name = record.display_name
    source.publication_policy = record.publication_policy
    source.confidence = record.confidence
    source.attribution = record.attribution
    source.last_seen_at = datetime.now(UTC)
    source.metadata_ = {**source.metadata_, **record.metadata}


def _new_mosque(record: DiscoveryRecord) -> Mosque:
    mosque = Mosque(
        id=uuid.uuid4(),
        name=record.name,
        normalized_name=normalize_mosque_name(record.name),
        address_line1=record.address_line1,
        address_line2=record.address_line2,
        city=record.city,
        county=record.county,
        postcode=record.postcode,
        country=record.country,
        website_url=record.website_url,
        status=MosqueStatus.NEEDS_REVIEW,
    )
    if record.latitude is not None and record.longitude is not None:
        mosque.location = WKTElement(
            f"POINT({record.longitude} {record.latitude})",
            srid=4326,
        )
    return mosque


def _apply_mosque_fields(mosque: Mosque, record: DiscoveryRecord) -> None:
    mosque.name = record.name
    mosque.normalized_name = normalize_mosque_name(record.name)
    mosque.address_line1 = record.address_line1
    mosque.address_line2 = record.address_line2
    mosque.city = record.city
    mosque.county = record.county
    mosque.postcode = record.postcode
    mosque.country = record.country
    mosque.website_url = record.website_url
    if record.latitude is not None and record.longitude is not None:
        mosque.location = WKTElement(
            f"POINT({record.longitude} {record.latitude})",
            srid=4326,
        )


async def _ensure_alias(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    alias: str,
    source_type: SourceType,
) -> None:
    normalized = normalize_mosque_name(alias)
    existing = await session.scalar(
        select(MosqueAlias).where(
            MosqueAlias.mosque_id == mosque_id,
            MosqueAlias.normalized_alias == normalized,
        )
    )
    if existing is not None:
        return
    session.add(
        MosqueAlias(
            id=uuid.uuid4(),
            mosque_id=mosque_id,
            alias=alias,
            normalized_alias=normalized,
            source_type=source_type,
        )
    )


async def _create_match_review(
    session: AsyncSession,
    record: DiscoveryRecord,
    match: DiscoveryMatch,
    *,
    source_id: uuid.UUID | None,
) -> None:
    review = IdentityMatchReview(
        id=uuid.uuid4(),
        source_id=source_id,
        proposed_mosque_id=match.mosque_id,
        score=match.score,
        decision=match.decision.value,
        reasons={"reasons": match.reasons, "record_external_id": record.external_id},
        alternatives={
            "candidates": [
                {
                    "mosque_id": str(item.mosque_id),
                    "score": item.score,
                    "reasons": item.reasons,
                }
                for item in match.alternatives
            ]
        },
        status="pending",
    )
    session.add(review)


def mosque_coordinates(mosque: Mosque) -> tuple[float | None, float | None]:
    if mosque.location is None:
        return None, None
    try:
        shape = to_shape(mosque.location)
        return shape.y, shape.x
    except Exception:  # noqa: BLE001
        return None, None
