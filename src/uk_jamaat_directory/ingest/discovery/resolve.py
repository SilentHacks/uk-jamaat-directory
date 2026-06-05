from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from uk_jamaat_directory.domain import MosqueStatus, SourceType
from uk_jamaat_directory.geo.location import set_mosque_point
from uk_jamaat_directory.ingest.discovery.matching import (
    GEO_CANDIDATE_METERS,
    decide_match,
    distance_meters,
    mosque_coordinates,
    score_mosque_candidate,
)
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
            await _apply_newer_source_name(session, mosque, record, incoming_source_id=source.id)
        await _accept_pending_reviews_for_source(
            session,
            source_id=source.id,
            mosque_id=mosque.id,
            record=record,
            match=DiscoveryMatch(
                decision=MatchDecision.AUTO_LINK,
                mosque_id=mosque.id,
                reasons=["existing_source_link"],
            ),
        )
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
        await _upsert_match_review(session, record, match, source_id=source.id)
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
        only_empty = outcome == ResolveOutcome.AUTO_LINK_MATCH
        _apply_mosque_fields(mosque, record, only_empty=only_empty)
        if only_empty:
            await _apply_newer_source_name(
                session,
                mosque,
                record,
                incoming_source_id=source.id if source is not None else None,
            )

    if outcome == ResolveOutcome.AUTO_LINK_MATCH:
        await _accept_pending_reviews_for_source(
            session,
            source_id=source.id,
            mosque_id=mosque.id,
            record=record,
            match=match,
        )

    for alias in record.aliases:
        await _ensure_alias(session, mosque.id, alias, record.source_type)

    await session.flush()
    return ResolvedDiscovery(mosque=mosque, source=source, match=match, outcome=outcome)


async def _score_candidates(
    session: AsyncSession,
    record: DiscoveryRecord,
) -> list[ScoredMosqueCandidate]:
    stmt = select(Mosque).options(selectinload(Mosque.aliases))
    if record.country:
        stmt = stmt.where(Mosque.country == record.country)

    candidate_filters = []
    record_postcode = normalize_postcode(record.postcode)
    if record_postcode:
        compact = record_postcode.replace(" ", "")
        candidate_filters.append(
            func.upper(func.replace(func.coalesce(Mosque.postcode, ""), " ", "")) == compact
        )

    if record.city:
        normalized_city = normalize_city(record.city)
        if normalized_city:
            candidate_filters.append(func.lower(Mosque.city) == normalized_city)

    if record.latitude is not None and record.longitude is not None:
        from geoalchemy2.functions import ST_DWithin

        from uk_jamaat_directory.geo.search import point_wkt

        origin = point_wkt(record.latitude, record.longitude)
        candidate_filters.append(ST_DWithin(Mosque.location, origin, float(GEO_CANDIDATE_METERS)))

    if candidate_filters:
        stmt = stmt.where(or_(*candidate_filters))
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
    if record.country and mosque.country and record.country != mosque.country:
        return False

    record_postcode = normalize_postcode(record.postcode)
    mosque_postcode = normalize_postcode(mosque.postcode)
    if record_postcode and mosque_postcode and record_postcode == mosque_postcode:
        return True

    distance_m = distance_meters(record.latitude, record.longitude, *mosque_coordinates(mosque))
    if distance_m is not None and distance_m <= GEO_CANDIDATE_METERS:
        return True

    if record_postcode and mosque_postcode:
        return False

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


async def _apply_newer_source_name(
    session: AsyncSession,
    mosque: Mosque,
    record: DiscoveryRecord,
    *,
    incoming_source_id: uuid.UUID | None,
) -> None:
    record_date = _source_record_datetime(record.metadata)
    if record_date is None or normalize_mosque_name(mosque.name) == normalize_mosque_name(
        record.name
    ):
        return

    latest_existing_date = await _latest_linked_source_record_datetime(
        session,
        mosque.id,
        exclude_source_id=incoming_source_id,
    )
    if latest_existing_date is None or record_date > latest_existing_date:
        mosque.name = record.name
        mosque.normalized_name = normalize_mosque_name(record.name)


async def _latest_linked_source_record_datetime(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    *,
    exclude_source_id: uuid.UUID | None,
) -> datetime | None:
    stmt = select(MosqueSource).where(MosqueSource.mosque_id == mosque_id)
    if exclude_source_id is not None:
        stmt = stmt.where(MosqueSource.id != exclude_source_id)
    sources = (await session.scalars(stmt)).all()
    dates = [
        parsed
        for source in sources
        if (parsed := _source_record_datetime(source.metadata_)) is not None
    ]
    if not dates:
        return None
    return max(dates)


_SOURCE_RECORD_DATE_KEYS = (
    "source_record_updated_at",
    "source_record_created_at",
    "updated_at",
    "last_updated",
    "modified_at",
    "date_added",
    "created_at",
)


def _source_record_datetime(metadata: dict[str, object]) -> datetime | None:
    for key in _SOURCE_RECORD_DATE_KEYS:
        raw = metadata.get(key)
        if raw is None:
            continue
        parsed = _parse_datetime(raw)
        if parsed is not None:
            return parsed
    return None


def _parse_datetime(raw: object) -> datetime | None:
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


async def _upsert_match_review(
    session: AsyncSession,
    record: DiscoveryRecord,
    match: DiscoveryMatch,
    *,
    source_id: uuid.UUID | None,
) -> None:
    review = None
    if source_id is not None:
        review = await session.scalar(
            select(IdentityMatchReview).where(
                IdentityMatchReview.source_id == source_id,
                IdentityMatchReview.status == "pending",
            )
        )

    if review is None:
        review = IdentityMatchReview(
            id=uuid.uuid4(),
            source_id=source_id,
            status="pending",
        )
        session.add(review)

    _apply_review_match(review, record, match)


async def _accept_pending_reviews_for_source(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    mosque_id: uuid.UUID,
    record: DiscoveryRecord,
    match: DiscoveryMatch,
) -> None:
    reviews = (
        await session.scalars(
            select(IdentityMatchReview).where(
                IdentityMatchReview.source_id == source_id,
                IdentityMatchReview.status == "pending",
            )
        )
    ).all()
    for review in reviews:
        _apply_review_match(review, record, match)
        review.proposed_mosque_id = mosque_id
        review.decision = MatchDecision.AUTO_LINK.value
        review.status = "accepted"
        review.reviewer = "resolver"
        review.reviewed_at = datetime.now(UTC)


def _apply_review_match(
    review: IdentityMatchReview,
    record: DiscoveryRecord,
    match: DiscoveryMatch,
) -> None:
    review.proposed_mosque_id = match.mosque_id
    review.score = match.score
    review.decision = match.decision.value
    review.reasons = {"reasons": match.reasons, "record_external_id": record.external_id}
    review.alternatives = {
        "candidates": [
            {
                "mosque_id": str(item.mosque_id),
                "score": item.score,
                "reasons": item.reasons,
            }
            for item in match.alternatives
        ]
    }
