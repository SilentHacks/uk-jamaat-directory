from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.api.deps import require_admin_key
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.models.core import MosqueSource
from uk_jamaat_directory.schemas.admin import (
    AdminAliasCreate,
    AdminBulkIdentityReviewAccept,
    AdminBulkMosqueActivate,
    AdminCandidateActionResponse,
    AdminCandidateListResponse,
    AdminCandidateReject,
    AdminCoverageResponse,
    AdminDiscoveryLeadCreate,
    AdminDiscoveryLeadResponse,
    AdminDuplicateBucket,
    AdminExtractorListResponse,
    AdminExtractorResponse,
    AdminIdentityActionResponse,
    AdminIdentityOverlapItem,
    AdminIdentityQualityResponse,
    AdminIdentityReviewAction,
    AdminIdentityReviewCandidate,
    AdminIdentityReviewListResponse,
    AdminIdentityReviewSummary,
    AdminMosqueCreate,
    AdminMosqueMerge,
    AdminMosqueResponse,
    AdminMosqueUpdate,
    AdminSourceAttach,
    AdminSourceHealthItem,
    AdminSourceHealthResponse,
    AdminSourceListResponse,
    AdminSourceResponse,
    AdminSourceUpdate,
)
from uk_jamaat_directory.services import (
    admin_identity,
    admin_reporting,
    admin_sources,
    schedule_moderation,
)
from uk_jamaat_directory.services.admin_sources import source_to_summary
from uk_jamaat_directory.services.errors import (
    DuplicateAliasError,
    MosqueNotFoundError,
    SourceNotFoundError,
)
from uk_jamaat_directory.services.schedule_moderation import candidate_to_summary

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class AdminHealthResponse(BaseModel):
    status: str


def _identity_review_to_summary(
    item: admin_identity.IdentityReviewItem,
) -> AdminIdentityReviewSummary:
    review = item.review
    source = item.source
    reasons = (review.reasons or {}).get("reasons") or []
    return AdminIdentityReviewSummary(
        review_id=review.id,
        source_id=review.source_id,
        source_type=source.source_type.value if source is not None else None,
        external_id=source.external_id if source is not None else None,
        display_name=source.display_name if source is not None else None,
        source_url=source.source_url if source is not None else None,
        decision=review.decision,
        score=float(review.score) if review.score is not None else None,
        reasons=[str(reason) for reason in reasons],
        status=review.status,
        candidates=[
            AdminIdentityReviewCandidate(
                mosque_id=candidate.mosque.id,
                name=candidate.mosque.name,
                status=candidate.mosque.status.value,
                postcode=candidate.mosque.postcode,
                city=candidate.mosque.city,
                score=candidate.score,
                reasons=candidate.reasons,
            )
            for candidate in item.candidates
        ],
    )


def _bulk_identity_response(
    result: admin_identity.BulkIdentityResult,
) -> AdminIdentityActionResponse:
    return AdminIdentityActionResponse(
        changed=result.changed,
        dry_run=result.dry_run,
        review_ids=result.review_ids or [],
        mosque_ids=result.mosque_ids or [],
    )


def _admin_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (MosqueNotFoundError, SourceNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, DuplicateAliasError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    raise exc


@router.get("/health", response_model=AdminHealthResponse)
async def admin_health() -> AdminHealthResponse:
    return AdminHealthResponse(status="ok")


@router.post("/mosques", response_model=AdminMosqueResponse, status_code=status.HTTP_201_CREATED)
async def create_mosque(
    payload: AdminMosqueCreate,
    session: AsyncSession = Depends(get_db_session),
) -> AdminMosqueResponse:
    mosque = await admin_identity.create_mosque(session, payload, actor="admin_api")
    await session.commit()
    return AdminMosqueResponse(
        directory_mosque_id=mosque.id,
        name=mosque.name,
        status=mosque.status.value,
    )


@router.patch("/mosques/{mosque_id}", response_model=AdminMosqueResponse)
async def update_mosque(
    mosque_id: uuid.UUID,
    payload: AdminMosqueUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> AdminMosqueResponse:
    try:
        mosque = await admin_identity.update_mosque(session, mosque_id, payload, actor="admin_api")
    except (MosqueNotFoundError, ValueError) as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminMosqueResponse(
        directory_mosque_id=mosque.id,
        name=mosque.name,
        status=mosque.status.value,
    )


@router.post(
    "/mosques/{mosque_id}/sources",
    status_code=status.HTTP_201_CREATED,
)
async def attach_source(
    mosque_id: uuid.UUID,
    payload: AdminSourceAttach,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    try:
        source = await admin_identity.attach_source(
            session,
            mosque_id,
            payload,
            actor="admin_api",
        )
    except MosqueNotFoundError as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return {"source_id": str(source.id)}


@router.post(
    "/mosques/{mosque_id}/aliases",
    status_code=status.HTTP_201_CREATED,
)
async def add_alias(
    mosque_id: uuid.UUID,
    payload: AdminAliasCreate,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    try:
        alias = await admin_identity.add_alias(session, mosque_id, payload, actor="admin_api")
    except (MosqueNotFoundError, DuplicateAliasError) as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return {"alias_id": str(alias.id)}


@router.post("/mosques/{mosque_id}/merge", response_model=AdminMosqueResponse)
async def merge_mosques(
    mosque_id: uuid.UUID,
    payload: AdminMosqueMerge,
    session: AsyncSession = Depends(get_db_session),
) -> AdminMosqueResponse:
    try:
        mosque = await admin_identity.merge_mosques(
            session,
            mosque_id,
            payload,
            actor="admin_api",
        )
    except (MosqueNotFoundError, ValueError) as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminMosqueResponse(
        directory_mosque_id=mosque.id,
        name=mosque.name,
        status=mosque.status.value,
    )


@router.get("/identity-report", response_model=AdminIdentityQualityResponse)
async def get_identity_report(
    session: AsyncSession = Depends(get_db_session),
) -> AdminIdentityQualityResponse:
    report = await admin_reporting.build_identity_quality_report(session)
    return AdminIdentityQualityResponse(
        generated_at=report.generated_at,
        mosque_count=report.mosque_count,
        active_mosque_count=report.active_mosque_count,
        status_counts=report.status_counts,
        source_count=report.source_count,
        source_type_counts=report.source_type_counts,
        policy_counts=report.policy_counts,
        source_overlaps=[
            AdminIdentityOverlapItem(
                source_set=item.source_set,
                mosque_count=item.mosque_count,
            )
            for item in report.source_overlaps
        ],
        linked_source_count=report.linked_source_count,
        unlinked_source_count=report.unlinked_source_count,
        pending_identity_reviews=report.pending_identity_reviews,
        missing_postcode_count=report.missing_postcode_count,
        missing_coordinates_count=report.missing_coordinates_count,
        missing_website_count=report.missing_website_count,
        active_missing_website_count=report.active_missing_website_count,
        duplicate_candidate_count=report.duplicate_candidate_count,
        duplicate_buckets=[
            AdminDuplicateBucket(
                normalized_name=item.normalized_name,
                postcode=item.postcode,
                mosque_count=item.mosque_count,
                mosque_ids=item.mosque_ids,
            )
            for item in report.duplicate_buckets
        ],
    )


@router.get("/identity-reviews", response_model=AdminIdentityReviewListResponse)
async def list_identity_reviews(
    status_filter: str = Query(default="pending", alias="status"),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> AdminIdentityReviewListResponse:
    try:
        result = await admin_identity.list_identity_reviews(
            session,
            status=status_filter,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    return AdminIdentityReviewListResponse(
        items=[_identity_review_to_summary(item) for item in result.items],
        count=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/identity-reviews/{review_id}/accept", response_model=AdminIdentityActionResponse)
async def accept_identity_review(
    review_id: uuid.UUID,
    payload: AdminIdentityReviewAction,
    session: AsyncSession = Depends(get_db_session),
) -> AdminIdentityActionResponse:
    try:
        review = await admin_identity.accept_identity_review(
            session,
            review_id,
            mosque_id=payload.mosque_id,
            actor="admin_api",
            reason=payload.reason,
        )
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminIdentityActionResponse(
        changed=1,
        review_ids=[review.id],
        mosque_ids=[review.proposed_mosque_id] if review.proposed_mosque_id else [],
    )


@router.post("/identity-reviews/{review_id}/reject", response_model=AdminIdentityActionResponse)
async def reject_identity_review(
    review_id: uuid.UUID,
    payload: AdminIdentityReviewAction,
    session: AsyncSession = Depends(get_db_session),
) -> AdminIdentityActionResponse:
    try:
        review = await admin_identity.reject_identity_review(
            session,
            review_id,
            actor="admin_api",
            reason=payload.reason,
        )
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminIdentityActionResponse(changed=1, review_ids=[review.id])


@router.post("/identity-reviews/bulk-accept", response_model=AdminIdentityActionResponse)
async def bulk_accept_identity_reviews(
    payload: AdminBulkIdentityReviewAccept,
    session: AsyncSession = Depends(get_db_session),
) -> AdminIdentityActionResponse:
    result = await admin_identity.bulk_accept_identity_reviews(
        session,
        min_score=payload.min_score,
        limit=payload.limit,
        dry_run=payload.dry_run,
        actor="admin_api",
    )
    if not payload.dry_run:
        await session.commit()
    return _bulk_identity_response(result)


@router.post("/identity/mosques/bulk-activate", response_model=AdminIdentityActionResponse)
async def bulk_activate_reviewed_mosques(
    payload: AdminBulkMosqueActivate,
    session: AsyncSession = Depends(get_db_session),
) -> AdminIdentityActionResponse:
    try:
        result = await admin_identity.bulk_activate_reviewed_mosques(
            session,
            source_type=payload.source_type,
            require_public_source=payload.require_public_source,
            limit=payload.limit,
            dry_run=payload.dry_run,
            actor="admin_api",
        )
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    if not payload.dry_run:
        await session.commit()
    return _bulk_identity_response(result)


@router.post("/discovery-leads", response_model=AdminDiscoveryLeadResponse)
async def create_discovery_lead(
    payload: AdminDiscoveryLeadCreate,
    session: AsyncSession = Depends(get_db_session),
) -> AdminDiscoveryLeadResponse:
    lead_id = await admin_identity.record_discovery_lead(
        session,
        query=payload.query,
        notes=payload.notes,
        location_hint=payload.location_hint,
        actor="admin_api",
        provider=payload.provider,
    )
    await session.commit()
    return AdminDiscoveryLeadResponse(
        lead_id=lead_id,
        status="recorded",
        message=(
            "Discovery lead stored for admin review only. "
            "Do not publish Google-derived facts as Directory data."
        ),
    )


@router.get("/candidates", response_model=AdminCandidateListResponse)
async def list_schedule_candidates(
    status_filter: str | None = Query(default=None, alias="status"),
    source_id: uuid.UUID | None = Query(default=None),
    mosque_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> AdminCandidateListResponse:
    parsed_status: CandidateStatus | None = None
    if status_filter:
        try:
            parsed_status = CandidateStatus(status_filter)
        except ValueError as exc:
            allowed = ", ".join(status.value for status in CandidateStatus)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid status; allowed values: {allowed}",
            ) from exc
    result = await schedule_moderation.list_candidates(
        session,
        status=parsed_status,
        source_id=source_id,
        mosque_id=mosque_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AdminCandidateListResponse(
        items=[candidate_to_summary(item) for item in result.items],
        count=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post("/candidates/{candidate_id}/approve", response_model=AdminCandidateActionResponse)
async def approve_schedule_candidate(
    candidate_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AdminCandidateActionResponse:
    try:
        candidate = await schedule_moderation.approve_candidate(
            session,
            candidate_id,
            actor="admin_api",
        )
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminCandidateActionResponse(
        candidate_id=candidate.id,
        status=candidate.status.value,
    )


@router.post("/candidates/{candidate_id}/reject", response_model=AdminCandidateActionResponse)
async def reject_schedule_candidate(
    candidate_id: uuid.UUID,
    payload: AdminCandidateReject,
    session: AsyncSession = Depends(get_db_session),
) -> AdminCandidateActionResponse:
    try:
        candidate = await schedule_moderation.reject_candidate(
            session,
            candidate_id,
            actor="admin_api",
            reason=payload.reason,
        )
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminCandidateActionResponse(
        candidate_id=candidate.id,
        status=candidate.status.value,
    )


@router.get("/sources", response_model=AdminSourceListResponse)
async def list_sources(
    mosque_id: uuid.UUID | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> AdminSourceListResponse:
    items, total = await admin_sources.list_sources(
        session,
        mosque_id=mosque_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return AdminSourceListResponse(
        items=[source_to_summary(item) for item in items],
        count=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/sources/{source_id}", response_model=AdminSourceResponse)
async def update_source(
    source_id: uuid.UUID,
    payload: AdminSourceUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> AdminSourceResponse:
    try:
        source = await admin_sources.update_source(
            session,
            source_id,
            payload,
            actor="admin_api",
        )
    except SourceNotFoundError as exc:
        raise _admin_http_error(exc) from exc
    except ValueError as exc:
        raise _admin_http_error(exc) from exc
    await session.commit()
    return AdminSourceResponse(
        source_id=source.id,
        directory_mosque_id=source.mosque_id,
        source_type=source.source_type.value,
        external_id=source.external_id,
        publication_policy=source.publication_policy.value,
        confidence=source.confidence.value,
    )


@router.get("/coverage", response_model=AdminCoverageResponse)
async def get_coverage(
    session: AsyncSession = Depends(get_db_session),
) -> AdminCoverageResponse:
    report = await admin_reporting.build_admin_coverage(session)
    return AdminCoverageResponse(
        generated_at=report.generated_at,
        mosque_count=report.mosque_count,
        active_mosque_count=report.active_mosque_count,
        source_count=report.source_count,
        pending_candidates=report.pending_candidates,
        approved_candidates=report.approved_candidates,
        rejected_candidates=report.rejected_candidates,
        open_corrections=report.open_corrections,
        open_claims=report.open_claims,
        policy_counts=report.policy_counts,
        source_type_counts=report.source_type_counts,
        stale_source_count=report.stale_source_count,
        pending_identity_reviews=report.pending_identity_reviews,
        missing_postcode_count=report.missing_postcode_count,
        missing_coordinates_count=report.missing_coordinates_count,
        missing_website_count=report.missing_website_count,
        duplicate_candidate_count=report.duplicate_candidate_count,
    )


@router.get("/source-health", response_model=AdminSourceHealthResponse)
async def get_source_health(
    mosque_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> AdminSourceHealthResponse:
    rows, total = await admin_reporting.list_source_health(
        session,
        mosque_id=mosque_id,
        limit=limit,
        offset=offset,
    )
    items = [
        AdminSourceHealthItem(
            source_id=health.source_id,
            directory_mosque_id=source.mosque_id,
            source_type=source.source_type.value,
            external_id=source.external_id,
            freshness_status=health.freshness_status.value,
            next_7_days_coverage=health.next_7_days_coverage,
            last_success_at=health.last_success_at,
            last_failure_at=health.last_failure_at,
            consecutive_failures=health.consecutive_failures,
            message=health.message,
        )
        for health, source in rows
    ]
    return AdminSourceHealthResponse(items=items, count=total)


async def _assignment_to_response(session, source: MosqueSource) -> AdminExtractorResponse:
    from uk_jamaat_directory.models.core import SourceExtractorAssignment

    assignment = await session.get(SourceExtractorAssignment, source.id)
    if assignment is None:
        return AdminExtractorResponse(
            source_id=source.id,
            extractor_key=None,
            extractor_version=None,
            status="unassigned",
            run_frequency="manual",
            run_timezone="Europe/London",
            next_run_at=None,
            last_run_at=None,
            last_success_at=None,
            last_failure_at=None,
            consecutive_failures=0,
            last_error=None,
        )
    return AdminExtractorResponse(
        source_id=source.id,
        extractor_key=assignment.extractor_key,
        extractor_version=assignment.extractor_version,
        status=assignment.status,
        run_frequency=assignment.run_frequency,
        run_timezone=assignment.run_timezone,
        next_run_at=assignment.next_run_at,
        last_run_at=assignment.last_run_at,
        last_success_at=assignment.last_success_at,
        last_failure_at=assignment.last_failure_at,
        consecutive_failures=assignment.consecutive_failures,
        last_error=assignment.last_error,
    )


@router.get(
    "/sources/{source_id}/extractor",
    response_model=AdminExtractorResponse,
)
async def get_source_extractor(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AdminExtractorResponse:
    source = await session.get(MosqueSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found"
        )
    return await _assignment_to_response(session, source)


@router.post(
    "/sources/{source_id}/extractor/sync",
    response_model=AdminExtractorResponse,
)
async def sync_source_extractor(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AdminExtractorResponse:
    from uk_jamaat_directory.ingest.extract.repo_extractors.sync import (
        sync_repo_extractors,
    )

    source = await session.get(MosqueSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found"
        )
    await sync_repo_extractors(session, source_id=source_id)
    await session.commit()
    return await _assignment_to_response(session, source)


@router.post(
    "/sources/{source_id}/extractor/disable",
    response_model=AdminExtractorResponse,
)
async def disable_source_extractor(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AdminExtractorResponse:
    from uk_jamaat_directory.models.core import SourceExtractorAssignment

    source = await session.get(MosqueSource, source_id)
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found"
        )
    assignment = await session.get(SourceExtractorAssignment, source_id)
    if assignment is not None:
        assignment.status = "disabled"
        await session.commit()
    return await _assignment_to_response(session, source)


@router.get("/extractors", response_model=AdminExtractorListResponse)
async def list_extractors(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> AdminExtractorListResponse:
    from sqlalchemy import select

    from uk_jamaat_directory.models.core import SourceExtractorAssignment

    stmt = select(SourceExtractorAssignment)
    if status_filter is not None:
        stmt = stmt.where(SourceExtractorAssignment.status == status_filter)
    stmt = stmt.order_by(SourceExtractorAssignment.source_id).offset(offset).limit(limit)
    assignments = (await session.execute(stmt)).scalars().all()
    items: list[AdminExtractorResponse] = []
    for assignment in assignments:
        source = await session.get(MosqueSource, assignment.source_id)
        if source is None:
            continue
        items.append(
            AdminExtractorResponse(
                source_id=source.id,
                extractor_key=assignment.extractor_key,
                extractor_version=assignment.extractor_version,
                status=assignment.status,
                run_frequency=assignment.run_frequency,
                run_timezone=assignment.run_timezone,
                next_run_at=assignment.next_run_at,
                last_run_at=assignment.last_run_at,
                last_success_at=assignment.last_success_at,
                last_failure_at=assignment.last_failure_at,
                consecutive_failures=assignment.consecutive_failures,
                last_error=assignment.last_error,
            )
        )
    return AdminExtractorListResponse(items=items, count=len(items))
