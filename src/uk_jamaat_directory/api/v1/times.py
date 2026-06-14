from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.api.cache import cache_control
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.schemas.public import NearbyTimesResponse
from uk_jamaat_directory.services import public_reads

router = APIRouter(
    prefix="/times", tags=["times"], dependencies=[cache_control("public, max-age=60")]
)


@router.get("/nearby", response_model=NearbyTimesResponse)
async def get_nearby_times(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius_m: float = Query(default=1000, ge=50, le=50000),
    on: date | None = Query(default=None, alias="date"),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> NearbyTimesResponse:
    return await public_reads.get_nearby_times(
        session,
        latitude=lat,
        longitude=lng,
        radius_m=radius_m,
        on_date=on or date.today(),
        limit=limit,
    )
