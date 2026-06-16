"""Admin UI pipeline: source health, extractor assignments, crawl trigger."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.models.core import ExtractorAuthoringTask, SourceExtractorAssignment
from uk_jamaat_directory.services import admin_reporting
from uk_jamaat_directory.tasks.crawl import process_source_task
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.admin.common import (
    PAGE_SIZE,
    no_store,
    safe_redirect_target,
    trigger_task,
)
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin")
require_admin = Depends(auth.require_admin_session)


@router.get("/pipeline", response_class=HTMLResponse, dependencies=[require_admin])
async def pipeline(
    request: Request,
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    health_rows, health_total = await admin_reporting.list_source_health(
        session, limit=PAGE_SIZE, offset=offset
    )
    assignments = list(
        (
            await session.execute(
                select(SourceExtractorAssignment)
                .order_by(SourceExtractorAssignment.next_run_at.asc().nullsfirst())
                .limit(PAGE_SIZE)
            )
        )
        .scalars()
        .all()
    )
    authoring_rows = list(
        (
            await session.execute(
                select(ExtractorAuthoringTask)
                .order_by(ExtractorAuthoringTask.updated_at.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    authoring_counts = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(ExtractorAuthoringTask.status, func.count()).group_by(
                    ExtractorAuthoringTask.status
                )
            )
        ).all()
    }
    return no_store(
        render(
            request,
            "admin/pipeline.html",
            {
                "health_rows": health_rows,
                "health_total": health_total,
                "assignments": assignments,
                "authoring_rows": authoring_rows,
                "authoring_counts": authoring_counts,
                "offset": offset,
                "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < health_total else None,
                "prev_offset": offset - PAGE_SIZE if offset - PAGE_SIZE >= 0 else None,
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


@router.post("/sources/{source_id}/crawl", dependencies=[require_admin])
async def source_crawl(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    redirect_to: str = Form(default="/admin/pipeline"),
):
    target = safe_redirect_target(redirect_to, "/admin/pipeline")
    return trigger_task(
        request,
        csrf_token,
        task=process_source_task,
        ok_msg="Crawl queued",
        redirect_to=target,
        args=(str(source_id),),
    )
