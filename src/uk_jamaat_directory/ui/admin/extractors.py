"""Admin UI extractor review dashboard: list, preview, attention, recrawl."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import ArtifactStatus
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import ExtractorArtifact
from uk_jamaat_directory.ingest.extract.repo_extractors.runner import (
    build_sandbox_payload,
    run_sandbox,
)
from uk_jamaat_directory.models.core import (
    Mosque,
    MosqueSource,
    SourceArtifact,
    SourceExtractorAssignment,
)
from uk_jamaat_directory.storage import S3Storage
from uk_jamaat_directory.tasks.crawl import process_source_task
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.admin.common import (
    PAGE_SIZE,
    check_csrf,
    no_store,
    safe_redirect_target,
    trigger_task,
)
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin")
require_admin = Depends(auth.require_admin_session)


def _assignment_row_context(
    assignment: SourceExtractorAssignment | None,
    source: MosqueSource,
    mosque: Mosque | None,
) -> dict:
    return {
        "Assignment": assignment,
        "Source": source,
        "Mosque": mosque,
    }


@router.get("/extractors", response_class=HTMLResponse, dependencies=[require_admin])
async def extractors_list(
    request: Request,
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    frequency: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    if status == "missing_script":
        stmt = (
            select(MosqueSource, Mosque, SourceExtractorAssignment)
            .join(Mosque, MosqueSource.mosque_id == Mosque.id, isouter=True)
            .outerjoin(
                SourceExtractorAssignment,
                MosqueSource.id == SourceExtractorAssignment.source_id,
            )
            .where(SourceExtractorAssignment.source_id.is_(None))
        )
        count_stmt = (
            select(func.count())
            .select_from(MosqueSource)
            .outerjoin(
                SourceExtractorAssignment,
                MosqueSource.id == SourceExtractorAssignment.source_id,
            )
            .where(SourceExtractorAssignment.source_id.is_(None))
        )
    else:
        stmt = (
            select(SourceExtractorAssignment, MosqueSource, Mosque)
            .join(MosqueSource, SourceExtractorAssignment.source_id == MosqueSource.id)
            .join(Mosque, MosqueSource.mosque_id == Mosque.id, isouter=True)
        )
        count_stmt = (
            select(func.count())
            .select_from(SourceExtractorAssignment)
            .join(MosqueSource, SourceExtractorAssignment.source_id == MosqueSource.id)
        )

        if status == "active":
            stmt = stmt.where(SourceExtractorAssignment.status == "active")
            count_stmt = count_stmt.where(SourceExtractorAssignment.status == "active")
        elif status == "needs_attention":
            stmt = stmt.where(
                SourceExtractorAssignment.metadata_["needs_attention"].astext == "true"
            )
            count_stmt = count_stmt.where(
                SourceExtractorAssignment.metadata_["needs_attention"].astext == "true"
            )

        if frequency:
            stmt = stmt.where(SourceExtractorAssignment.run_frequency == frequency)
            count_stmt = count_stmt.where(SourceExtractorAssignment.run_frequency == frequency)

    if q and q.strip():
        pattern = f"%{q.strip()}%"
        if status == "missing_script":
            stmt = stmt.where(
                or_(
                    Mosque.name.ilike(pattern),
                    MosqueSource.source_url.ilike(pattern),
                )
            )
            count_stmt = count_stmt.where(
                or_(
                    Mosque.name.ilike(pattern),
                    MosqueSource.source_url.ilike(pattern),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Mosque.name.ilike(pattern),
                    MosqueSource.source_url.ilike(pattern),
                )
            )
            count_stmt = count_stmt.where(
                or_(
                    Mosque.name.ilike(pattern),
                    MosqueSource.source_url.ilike(pattern),
                )
            )

    if status == "missing_script":
        stmt = stmt.order_by(MosqueSource.source_url.asc())
    else:
        stmt = stmt.order_by(SourceExtractorAssignment.next_run_at.asc().nullsfirst())

    total = int((await session.execute(count_stmt)).scalar_one())
    raw_rows = list((await session.execute(stmt.offset(offset).limit(PAGE_SIZE))).all())

    rows = [_assignment_row_context(*row) for row in raw_rows]

    return no_store(
        render(
            request,
            "admin/extractors.html",
            {
                "rows": rows,
                "total": total,
                "q": q or "",
                "status_filter": status or "",
                "freq_filter": frequency or "",
                "offset": offset,
                "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < total else None,
                "prev_offset": offset - PAGE_SIZE if offset - PAGE_SIZE >= 0 else None,
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


@router.post("/extractors/{source_id}/preview", dependencies=[require_admin])
async def extractor_preview(
    request: Request,
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    source = await session.get(MosqueSource, source_id)
    if source is None:
        return no_store(
            render(
                request,
                "admin/extractor_preview.html",
                {
                    "error": "Source not found.",
                    "source_id": str(source_id),
                    "csrf_token": auth.issue_csrf_token(request),
                },
            )
        )

    assignment = await session.get(SourceExtractorAssignment, source_id)
    if assignment is None:
        return no_store(
            render(
                request,
                "admin/extractor_preview.html",
                {
                    "error": "No extractor assigned to this source.",
                    "source_id": str(source_id),
                    "csrf_token": auth.issue_csrf_token(request),
                },
            )
        )

    artifact_stmt = (
        select(SourceArtifact)
        .where(SourceArtifact.source_id == source_id)
        .where(SourceArtifact.status == ArtifactStatus.FETCHED)
        .order_by(SourceArtifact.created_at.desc())
        .limit(1)
    )
    artifact = (await session.execute(artifact_stmt)).scalar_one_or_none()
    if artifact is None or not artifact.object_key:
        return no_store(
            render(
                request,
                "admin/extractor_preview.html",
                {
                    "error": "No stored artifacts found for this source. Please crawl first.",
                    "source_id": str(source_id),
                    "csrf_token": auth.issue_csrf_token(request),
                },
            )
        )

    try:
        storage = S3Storage(settings)
        body = await storage.get_bytes(artifact.object_key)
    except Exception as exc:
        return no_store(
            render(
                request,
                "admin/extractor_preview.html",
                {
                    "error": f"Failed to read artifact from storage: {exc}",
                    "source_id": str(source_id),
                    "csrf_token": auth.issue_csrf_token(request),
                },
            )
        )

    ext_artifact = ExtractorArtifact(
        target_label="timetable",
        target_url=artifact.fetched_url or source.source_url or "",
        content_type=artifact.content_type,
        body=body,
    )

    payload = build_sandbox_payload(
        extractor_key=assignment.extractor_key,
        source_id=str(source.id),
        mosque_name=source.display_name or "Unknown Mosque",
        mosque_id=str(source.mosque_id) if source.mosque_id else None,
        source_url=source.source_url or "",
        timezone=assignment.run_timezone,
        artifacts={"timetable": ext_artifact},
    )

    sandbox = await run_sandbox(assignment.extractor_key, payload, settings=settings)

    if not sandbox.ok or sandbox.result is None:
        return no_store(
            render(
                request,
                "admin/extractor_preview.html",
                {
                    "error": sandbox.error or "Sandbox execution failed.",
                    "source_id": str(source_id),
                    "csrf_token": auth.issue_csrf_token(request),
                },
            )
        )

    result = sandbox.result
    meta = dict(assignment.metadata_ or {})
    needs_attention = meta.get("needs_attention", False)
    notes = meta.get("attention_notes", "")

    return no_store(
        render(
            request,
            "admin/extractor_preview.html",
            {
                "preview": result,
                "source_id": str(source_id),
                "csrf_token": auth.issue_csrf_token(request),
                "needs_attention": needs_attention,
                "notes": notes,
                "duration_ms": sandbox.duration_ms,
            },
        )
    )


@router.post("/extractors/{source_id}/attention", dependencies=[require_admin])
async def extractor_attention(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    needs_attention: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    if not check_csrf(request, csrf_token):
        return no_store(
            HTMLResponse(
                '<tr><td colspan="5" class="flash err">Session expired. Please refresh.</td></tr>',
                status_code=403,
            )
        )

    assignment = await session.get(SourceExtractorAssignment, source_id)
    if assignment is None:
        return no_store(
            HTMLResponse(
                '<tr><td colspan="5" class="flash err">Assignment not found.</td></tr>',
                status_code=404,
            )
        )

    meta = dict(assignment.metadata_ or {})
    if needs_attention == "true":
        meta["needs_attention"] = True
        meta["attention_notes"] = notes.strip() if notes else ""
        meta["attention_updated_at"] = datetime.now(UTC).isoformat()
    else:
        meta.pop("needs_attention", None)
        meta.pop("attention_notes", None)
        meta.pop("attention_updated_at", None)

    assignment.metadata_ = meta
    await session.flush()

    source = await session.get(MosqueSource, source_id)
    mosque = await session.get(Mosque, source.mosque_id) if source and source.mosque_id else None

    ctx = _assignment_row_context(assignment, source, mosque)
    ctx["csrf_token"] = auth.issue_csrf_token(request)

    return no_store(
        render(
            request,
            "admin/extractor_row.html",
            ctx,
        )
    )


@router.post("/extractors/{source_id}/recrawl", dependencies=[require_admin])
async def extractor_recrawl(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    redirect_to: str = Form(default="/admin/extractors"),
):
    target = safe_redirect_target(redirect_to, "/admin/extractors")
    return trigger_task(
        request,
        csrf_token,
        task=process_source_task,
        ok_msg="Recrawl queued",
        redirect_to=target,
        args=(str(source_id),),
    )
