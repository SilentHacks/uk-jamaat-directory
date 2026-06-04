from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from uk_jamaat_directory.api.deps import require_admin_key

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class AdminHealthResponse(BaseModel):
    status: str


@router.get("/health", response_model=AdminHealthResponse)
async def admin_health() -> AdminHealthResponse:
    return AdminHealthResponse(status="ok")
