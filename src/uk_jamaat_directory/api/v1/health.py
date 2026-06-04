from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.db.session import get_db_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    name: str
    version: str
    environment: str
    status: str


class ReadinessResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        status="ok",
    )


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> ReadinessResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", database="unavailable")

    return ReadinessResponse(status="ok", database="ok")
