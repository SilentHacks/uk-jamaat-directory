from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.api.deps import require_admin_key
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.schemas.admin import (
    AdminAliasCreate,
    AdminDiscoveryLeadCreate,
    AdminDiscoveryLeadResponse,
    AdminMosqueCreate,
    AdminMosqueMerge,
    AdminMosqueResponse,
    AdminMosqueUpdate,
    AdminSourceAttach,
)
from uk_jamaat_directory.services import admin_identity
from uk_jamaat_directory.services.errors import DuplicateAliasError, MosqueNotFoundError

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class AdminHealthResponse(BaseModel):
    status: str


def _admin_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MosqueNotFoundError):
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
