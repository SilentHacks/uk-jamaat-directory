from __future__ import annotations

from fastapi import APIRouter

from uk_jamaat_directory.api.v1 import admin, health

api_router = APIRouter()
api_router.include_router(admin.router)
api_router.include_router(health.router)
