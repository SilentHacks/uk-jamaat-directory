"""Admin UI: shared-key login + management, moderation, and pipeline controls.

State-changing routes require an authenticated session (``require_admin_session``)
and a valid CSRF token submitted with the form. Heavy pipeline operations are
dispatched to Celery rather than run inline in the request.

The routes are split across focused modules (``auth_routes``, ``dashboard``,
``mosques``, ``moderation``, ``pipeline``) that share primitives from
``common``. Each sub-router carries the ``/admin`` prefix and they are stitched
together here into one router that ``main`` mounts.
"""

from __future__ import annotations

from fastapi import APIRouter

from uk_jamaat_directory.ui.admin import (
    auth_routes,
    dashboard,
    moderation,
    mosques,
    pipeline,
)

router = APIRouter(tags=["admin-ui"], include_in_schema=False)
router.include_router(auth_routes.router)
router.include_router(dashboard.router)
router.include_router(mosques.router)
router.include_router(moderation.router)
router.include_router(pipeline.router)

__all__ = ["router"]
