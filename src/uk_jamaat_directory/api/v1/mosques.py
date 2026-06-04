from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.schemas.public import MosqueDetailPublic, MosqueListResponse, TimesResponse
from uk_jamaat_directory.services import public_reads

router = APIRouter(prefix="/mosques", tags=["mosques"])


@router.get("", response_model=MosqueListResponse)
async def list_mosques(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    city: str | None = Query(default=None),
    postcode: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> MosqueListResponse:
    return await public_reads.list_mosques(
        session,
        limit=limit,
        offset=offset,
        city=city,
        postcode=postcode,
    )


@router.get("/search", response_model=MosqueListResponse)
async def search_mosques(
    q: str | None = Query(default=None),
    postcode: str | None = Query(default=None),
    city: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> MosqueListResponse:
    if not any([q, postcode, city]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of q, postcode, or city is required",
        )
    return await public_reads.search_mosques(
        session,
        query=q,
        postcode=postcode,
        city=city,
        limit=limit,
    )


@router.get("/{directory_mosque_id}", response_model=MosqueDetailPublic)
async def get_mosque(
    directory_mosque_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> MosqueDetailPublic:
    mosque = await public_reads.get_mosque(session, directory_mosque_id)
    if mosque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mosque not found")
    return mosque


@router.get("/{directory_mosque_id}/times", response_model=TimesResponse)
async def get_mosque_times(
    directory_mosque_id: uuid.UUID,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    session: AsyncSession = Depends(get_db_session),
) -> TimesResponse:
    resolved_from = from_date or date.today()
    resolved_to = to_date or resolved_from
    if resolved_to < resolved_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'to' must be on or after 'from'",
        )

    times = await public_reads.get_mosque_times(
        session,
        directory_mosque_id,
        from_date=resolved_from,
        to_date=resolved_to,
    )
    if times is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mosque not found")
    return times
