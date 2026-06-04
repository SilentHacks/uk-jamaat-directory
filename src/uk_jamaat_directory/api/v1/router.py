from __future__ import annotations

from fastapi import APIRouter

from uk_jamaat_directory.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
