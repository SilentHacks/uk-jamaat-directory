from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.schemas.public import SnapshotResponse
from uk_jamaat_directory.services import public_reads

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


@router.get("/latest", response_model=SnapshotResponse)
async def get_latest_snapshot(
    format: str | None = Query(default=None, pattern="^(ndjson|csv)$"),
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotResponse:
    snapshot = await public_reads.get_latest_snapshot(session, format_name=format)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No published snapshot")
    return snapshot


@router.get("/{version}", response_model=SnapshotResponse)
async def get_snapshot(
    version: str,
    format: str | None = Query(default=None, pattern="^(ndjson|csv)$"),
    session: AsyncSession = Depends(get_db_session),
) -> SnapshotResponse:
    snapshot = await public_reads.get_snapshot_by_version(session, version, format_name=format)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return snapshot
