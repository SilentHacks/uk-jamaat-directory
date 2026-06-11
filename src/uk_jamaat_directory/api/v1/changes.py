from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.api.cache import cache_control
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.schemas.public import ChangeFeedResponse
from uk_jamaat_directory.services import public_reads

router = APIRouter(
    prefix="/changes", tags=["changes"], dependencies=[cache_control("public, max-age=60")]
)


@router.get("", response_model=ChangeFeedResponse)
async def get_changes(
    since: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> ChangeFeedResponse:
    return await public_reads.get_changes(session, since=since, limit=limit)
