from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.api.deps import require_admin_key
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.schemas.admin import (
    AdminAliasCreate,
    AdminCandidateActionResponse,
    AdminCandidateListResponse,
    AdminCandidateReject,
    AdminCoverageResponse,
    AdminDiscoveryLeadCreate,
    AdminDiscoveryLeadResponse,
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
