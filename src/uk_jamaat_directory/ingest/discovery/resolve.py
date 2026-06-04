from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uk_jamaat_directory.domain import MosqueStatus, SourceType
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.matching import decide_match, score_mosque_candidate
from uk_jamaat_directory.ingest.discovery.records import (
    DiscoveryMatch,
    DiscoveryRecord,
    MatchDecision,
    ResolvedDiscovery,
    ResolveOutcome,
    ScoredMosqueCandidate,
)
from uk_jamaat_directory.ingest.normalize import (
    normalize_city,
    normalize_mosque_name,
    normalize_postcode,
)
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
) -> ResolvedDiscovery:
    """Link a discovery record to an existing mosque or create a reviewable mosque."""
    source = await _get_source(session, record.source_type, record.external_id)
    if source is not None and source.mosque_id is not None:
        mosque = await session.get_one(Mosque, source.mosque_id)
        _update_source(source, record)
        if is_public_source_policy(record.publication_policy):
            _apply_mosque_fields(mosque, record, only_empty=True)
        await session.flush()
        return ResolvedDiscovery(
            mosque=mosque,
            source=source,
            match=DiscoveryMatch(
                decision=MatchDecision.AUTO_LINK,
                mosque_id=mosque.id,
                reasons=["existing_source_link"],
            ),
            outcome=ResolveOutcome.EXISTING_SOURCE_LINK,
        )

    if source is not None:
        _update_source(source, record)

    candidates = await _score_candidates(session, record)
    match = decide_match(record, candidates)

    if match.decision == MatchDecision.NEEDS_REVIEW:
        if source is None:
            source = _new_source(record, mosque_id=None)
            session.add(source)
            await session.flush()
        else:
            _update_source(source, record)
        await _create_match_review(session, record, match, source_id=source.id)
        return ResolvedDiscovery(
            mosque=None,
            source=source,
            match=match,
            outcome=ResolveOutcome.NEEDS_REVIEW,
        )

    mosque: Mosque | None = None
    outcome: ResolveOutcome
    if match.decision == MatchDecision.AUTO_LINK and match.mosque_id is not None:
        mosque = await session.get_one(Mosque, match.mosque_id)
        outcome = ResolveOutcome.AUTO_LINK_MATCH
    elif match.decision == MatchDecision.CREATE_NEEDS_REVIEW:
        mosque = _new_mosque(record)
        session.add(mosque)
        await session.flush()
        outcome = ResolveOutcome.CREATED_NEEDS_REVIEW
    else:
        mosque = _new_mosque(record)
        session.add(mosque)
        await session.flush()
        outcome = ResolveOutcome.CREATED_NEEDS_REVIEW

    if source is None:
        source = _new_source(record, mosque_id=mosque.id)
        session.add(source)
    else:
        source.mosque_id = mosque.id
        _update_source(source, record)

    if is_public_source_policy(record.publication_policy):
        _apply_mosque_fields(mosque, record, only_empty=outcome == ResolveOutcome.AUTO_LINK_MATCH)

    for alias in record.aliases:
        await _ensure_alias(session, mosque.id, alias, record.source_type)

    await session.flush()
    return ResolvedDiscovery(mosque=mosque, source=source, match=match, outcome=outcome)


async def _score_candidates(
    session: AsyncSession,
    record: DiscoveryRecord,
) -> list[ScoredMosqueCandidate]:
    stmt = select(Mosque).options(selectinload(Mosque.aliases))
    record_postcode = normalize_postcode(record.postcode)
    if record_postcode:
        compact = record_postcode.replace(" ", "")
        stmt = stmt.where(
            func.upper(func.replace(func.coalesce(Mosque.postcode, ""), " ", "")) == compact
        )
    elif record.city:
        normalized_city = normalize_city(record.city)
        if normalized_city:
            stmt = stmt.where(func.lower(Mosque.city) == normalized_city)
        else:
            stmt = stmt.limit(500)
    else:
        stmt = stmt.limit(500)

    mosques = (await session.scalars(stmt)).all()

    scored: list[ScoredMosqueCandidate] = []
    for mosque in mosques:
        if not _is_plausible_candidate(record, mosque):
            continue
        candidate = score_mosque_candidate(record, mosque, aliases=mosque.aliases)
        if candidate is not None:
            scored.append(candidate)
    return scored


def _is_plausible_candidate(record: DiscoveryRecord, mosque: Mosque) -> bool:
    record_postcode = normalize_postcode(record.postcode)
    mosque_postcode = normalize_postcode(mosque.postcode)
    if record_postcode and mosque_postcode:
        return record_postcode == mosque_postcode
    record_city = normalize_city(record.city)
    mosque_city = normalize_city(mosque.city)
    if record_city and mosque_city:
        return record_city == mosque_city
    return True


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
    set_mosque_point(mosque, record.latitude, record.longitude)
    return mosque


def _apply_mosque_fields(
    mosque: Mosque,
    record: DiscoveryRecord,
    *,
    only_empty: bool = False,
) -> None:
    def set_field(field: str, value: object | None) -> None:
        if value is None:
            return
        current = getattr(mosque, field)
        if only_empty and current not in (None, ""):
            return
        setattr(mosque, field, value)

    set_field("name", record.name)
    if not only_empty or not mosque.normalized_name:
        mosque.normalized_name = normalize_mosque_name(record.name)
    set_field("address_line1", record.address_line1)
    set_field("address_line2", record.address_line2)
    set_field("city", record.city)
    set_field("county", record.county)
    set_field("postcode", record.postcode)
    set_field("country", record.country)
    set_field("website_url", record.website_url)
    if record.latitude is not None and record.longitude is not None:
        if not only_empty or mosque.location is None:
            set_mosque_point(mosque, record.latitude, record.longitude)


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
