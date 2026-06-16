"""Admin UI dashboard: coverage stats and recent source health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.services import admin_reporting
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.admin.common import no_store
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse, dependencies=[Depends(auth.require_admin_session)])
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    coverage = await admin_reporting.build_admin_coverage(session)
    health_rows, _ = await admin_reporting.list_source_health(session, limit=10)
    return no_store(
        render(
            request,
            "admin/dashboard.html",
            {
                "coverage": coverage,
                "health_rows": health_rows,
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )
