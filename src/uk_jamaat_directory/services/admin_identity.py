from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
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
from uk_jamaat_directory.services.public_policy import is_public_source_policy


@dataclass
class IdentityReviewCandidate:
    mosque: Mosque
    score: float
    reasons: list[str]


@dataclass
class IdentityReviewItem:
    review: IdentityMatchReview
    source: MosqueSource | None
    candidates: list[IdentityReviewCandidate]


@dataclass
class IdentityReviewList:
    items: list[IdentityReviewItem]
    total: int
    limit: int
    offset: int


@dataclass
class BulkIdentityResult:
    changed: int
    dry_run: bool = False
    review_ids: list[uuid.UUID] | None = None
    mosque_ids: list[uuid.UUID] | None = None


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


async def list_identity_reviews(
    session: AsyncSession,
    *,
    status: str = "pending",
    source_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> IdentityReviewList:
    stmt = (
        select(IdentityMatchReview, MosqueSource)
        .outerjoin(MosqueSource, IdentityMatchReview.source_id == MosqueSource.id)
        .where(IdentityMatchReview.status == status)
        .order_by(
            IdentityMatchReview.score.desc().nullslast(),
            IdentityMatchReview.created_at.asc(),
        )
        .offset(offset)
        .limit(limit)
    )
    count_stmt = (
        select(func.count())
        .select_from(IdentityMatchReview)
        .where(IdentityMatchReview.status == status)
    )
    if source_type is not None:
        parsed_source_type = SourceType(source_type)
        stmt = stmt.where(MosqueSource.source_type == parsed_source_type)
        count_stmt = count_stmt.join(MosqueSource).where(
            MosqueSource.source_type == parsed_source_type
        )

    rows = list((await session.execute(stmt)).all())
    items = [
        IdentityReviewItem(
            review=review,
            source=source,
            candidates=await _identity_review_candidates(session, review),
        )
        for review, source in rows
    ]
    total = int((await session.execute(count_stmt)).scalar_one())
    return IdentityReviewList(items=items, total=total, limit=limit, offset=offset)


async def accept_identity_review(
    session: AsyncSession,
    review_id: uuid.UUID,
    *,
    mosque_id: uuid.UUID | None = None,
    actor: str,
    reason: str | None = None,
) -> IdentityMatchReview:
    review = await _require_identity_review(session, review_id)
    if review.status != "pending":
        raise ValueError("identity review is not pending")
    if review.source_id is None:
        raise ValueError("identity review has no source to link")

    source = await session.get(MosqueSource, review.source_id)
    if source is None:
        raise ValueError("identity review source no longer exists")

    target_id = mosque_id or review.proposed_mosque_id or _single_candidate_id(review)
    if target_id is None:
        raise ValueError("accepting this review requires a mosque_id")
    if target_id not in _candidate_ids(review):
        raise ValueError("mosque_id is not one of the review candidates")

    mosque = await _require_mosque(session, target_id)
    source.mosque_id = mosque.id
    if source.display_name:
        await _ensure_alias(session, mosque.id, source.display_name, source.source_type)

    review.proposed_mosque_id = mosque.id
    review.status = "accepted"
    review.reviewer = actor
    review.reviewed_at = datetime.now(UTC)
    await _audit(
        session,
        actor=actor,
        action="accept_identity_review",
        entity_type="identity_match_review",
        entity_id=review.id,
        reason=reason,
        metadata={"source_id": str(source.id), "mosque_id": str(mosque.id)},
    )
    await session.flush()
    return review


async def reject_identity_review(
    session: AsyncSession,
    review_id: uuid.UUID,
    *,
    actor: str,
    reason: str | None = None,
) -> IdentityMatchReview:
    review = await _require_identity_review(session, review_id)
    if review.status != "pending":
        raise ValueError("identity review is not pending")
    review.status = "rejected"
    review.reviewer = actor
    review.reviewed_at = datetime.now(UTC)
    await _audit(
        session,
        actor=actor,
        action="reject_identity_review",
        entity_type="identity_match_review",
        entity_id=review.id,
        reason=reason,
        metadata={"source_id": str(review.source_id) if review.source_id else None},
    )
    await session.flush()
    return review


async def bulk_accept_identity_reviews(
    session: AsyncSession,
    *,
    min_score: float,
    limit: int,
    dry_run: bool,
    actor: str,
) -> BulkIdentityResult:
    reviews = (
        await session.scalars(
            select(IdentityMatchReview)
            .where(IdentityMatchReview.status == "pending")
            .where(IdentityMatchReview.score >= min_score)
            .order_by(
                IdentityMatchReview.score.desc().nullslast(),
                IdentityMatchReview.created_at.asc(),
            )
            .limit(limit)
        )
    ).all()
    eligible = [
        review
        for review in reviews
        if review.source_id is not None and _single_candidate_id(review) is not None
    ]
    review_ids: list[uuid.UUID] = []
    mosque_ids: list[uuid.UUID] = []
    if dry_run:
        for review in eligible:
            review_ids.append(review.id)
            candidate_id = _single_candidate_id(review)
            if candidate_id is not None:
                mosque_ids.append(candidate_id)
        return BulkIdentityResult(
            changed=len(eligible),
            dry_run=True,
            review_ids=review_ids,
            mosque_ids=mosque_ids,
        )

    for review in eligible:
        accepted = await accept_identity_review(
            session,
            review.id,
            mosque_id=_single_candidate_id(review),
            actor=actor,
            reason="bulk high-confidence single-candidate identity review",
        )
        review_ids.append(accepted.id)
        if accepted.proposed_mosque_id is not None:
            mosque_ids.append(accepted.proposed_mosque_id)
    return BulkIdentityResult(
        changed=len(review_ids),
        dry_run=False,
        review_ids=review_ids,
        mosque_ids=mosque_ids,
    )


async def bulk_activate_reviewed_mosques(
    session: AsyncSession,
    *,
    source_type: str | None,
    require_public_source: bool,
    limit: int,
    dry_run: bool,
    actor: str,
) -> BulkIdentityResult:
    parsed_source_type = SourceType(source_type) if source_type else None
    stmt = (
        select(Mosque)
        .join(MosqueSource, MosqueSource.mosque_id == Mosque.id)
        .where(Mosque.status == MosqueStatus.NEEDS_REVIEW)
        .distinct()
        .order_by(Mosque.name.asc())
        .limit(limit)
    )
    if parsed_source_type is not None:
        stmt = stmt.where(MosqueSource.source_type == parsed_source_type)

    mosques = (await session.scalars(stmt)).all()
    eligible: list[Mosque] = []
    for mosque in mosques:
        if await _mosque_has_pending_identity_review(session, mosque.id):
            continue
        if require_public_source and not await _mosque_has_public_source(session, mosque.id):
            continue
        eligible.append(mosque)

    mosque_ids = [mosque.id for mosque in eligible]
    if dry_run:
        return BulkIdentityResult(
            changed=len(eligible),
            dry_run=True,
            review_ids=[],
            mosque_ids=mosque_ids,
        )

    for mosque in eligible:
        mosque.status = MosqueStatus.ACTIVE
        await _audit(
            session,
            actor=actor,
            action="activate_reviewed_mosque",
            entity_type="mosque",
            entity_id=mosque.id,
            metadata={
                "source_type": parsed_source_type.value if parsed_source_type else None,
                "require_public_source": require_public_source,
            },
        )
    await session.flush()
    return BulkIdentityResult(
        changed=len(eligible),
        dry_run=False,
        review_ids=[],
        mosque_ids=mosque_ids,
    )


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


async def _require_identity_review(
    session: AsyncSession,
    review_id: uuid.UUID,
) -> IdentityMatchReview:
    review = await session.get(IdentityMatchReview, review_id)
    if review is None:
        raise ValueError(f"identity review not found: {review_id}")
    return review


async def _identity_review_candidates(
    session: AsyncSession,
    review: IdentityMatchReview,
) -> list[IdentityReviewCandidate]:
    candidates: list[IdentityReviewCandidate] = []
    for item in _candidate_items(review):
        mosque_id = item["mosque_id"]
        mosque = await session.get(Mosque, mosque_id)
        if mosque is None:
            continue
        candidates.append(
            IdentityReviewCandidate(
                mosque=mosque,
                score=float(item.get("score") or 0),
                reasons=list(item.get("reasons") or []),
            )
        )
    return candidates


def _candidate_items(review: IdentityMatchReview) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if review.proposed_mosque_id is not None:
        items.append(
            {
                "mosque_id": review.proposed_mosque_id,
                "score": float(review.score or 0),
                "reasons": list((review.reasons or {}).get("reasons") or []),
            }
        )
    for candidate in (review.alternatives or {}).get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        raw_id = candidate.get("mosque_id")
        try:
            mosque_id = raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
        if any(item["mosque_id"] == mosque_id for item in items):
            continue
        items.append(
            {
                "mosque_id": mosque_id,
                "score": float(candidate.get("score") or 0),
                "reasons": [str(reason) for reason in candidate.get("reasons") or []],
            }
        )
    return items


def _candidate_ids(review: IdentityMatchReview) -> set[uuid.UUID]:
    return {item["mosque_id"] for item in _candidate_items(review)}


def _single_candidate_id(review: IdentityMatchReview) -> uuid.UUID | None:
    candidates = _candidate_items(review)
    if len(candidates) != 1:
        return None
    return candidates[0]["mosque_id"]


async def _mosque_has_pending_identity_review(session: AsyncSession, mosque_id: uuid.UUID) -> bool:
    source_ids = (
        await session.scalars(select(MosqueSource.id).where(MosqueSource.mosque_id == mosque_id))
    ).all()
    if not source_ids:
        return False
    count = await session.scalar(
        select(func.count())
        .select_from(IdentityMatchReview)
        .where(IdentityMatchReview.source_id.in_(source_ids))
        .where(IdentityMatchReview.status == "pending")
    )
    return bool(count)


async def _mosque_has_public_source(session: AsyncSession, mosque_id: uuid.UUID) -> bool:
    sources = (
        await session.scalars(select(MosqueSource).where(MosqueSource.mosque_id == mosque_id))
    ).all()
    return any(is_public_source_policy(source.publication_policy) for source in sources)


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
