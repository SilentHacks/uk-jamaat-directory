from __future__ import annotations

from fastapi import APIRouter

from uk_jamaat_directory.api.v1 import admin, changes, health, mosques, snapshots, times

api_router = APIRouter()
api_router.include_router(admin.router)
api_router.include_router(health.router)
api_router.include_router(mosques.router)
api_router.include_router(times.router)
api_router.include_router(changes.router)
api_router.include_router(snapshots.router)
