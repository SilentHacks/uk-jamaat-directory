"""Admin UI moderation: candidate review and schedule pipeline triggers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import CandidateStatus
from uk_jamaat_directory.services import schedule_moderation
from uk_jamaat_directory.tasks.schedules import (
    publish_candidates_task,
    recompute_freshness_task,
    validate_candidates_task,
)
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.admin.common import (
    ADMIN_ACTOR,
    PAGE_SIZE,
    check_csrf,
    clean,
    no_store,
    redirect,
    safe_redirect_target,
    trigger_task,
)
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin")
require_admin = Depends(auth.require_admin_session)

#: Schedule pipeline triggers, keyed by URL slug -> (Celery task, flash message).
#: All three share the same CSRF-guard + enqueue + redirect flow, so they are
#: registered from this table rather than written out as near-identical handlers.
_SCHEDULE_TRIGGERS: dict[str, tuple[object, str]] = {
    "validate": (validate_candidates_task, "Validation queued"),
    "publish": (publish_candidates_task, "Publish queued"),
    "recompute-freshness": (recompute_freshness_task, "Freshness recompute queued"),
}


@router.get("/candidates", response_class=HTMLResponse, dependencies=[require_admin])
async def candidates_list(
    request: Request,
    status_filter: str | None = Query(default="pending", alias="status"),
    mosque_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    parsed_status = CandidateStatus(status_filter) if status_filter else None
    result = await schedule_moderation.list_candidates(
        session,
        status=parsed_status,
        mosque_id=mosque_id,
        limit=PAGE_SIZE,
        offset=offset,
    )
    summaries = [schedule_moderation.candidate_to_summary(c) for c in result.items]
    return no_store(
        render(
            request,
            "admin/candidates.html",
            {
                "candidates": summaries,
                "total": result.total,
                "status_filter": status_filter or "",
                "statuses": [s.value for s in CandidateStatus],
                "mosque_id": str(mosque_id) if mosque_id else "",
                "offset": offset,
                "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < result.total else None,
                "prev_offset": offset - PAGE_SIZE if offset - PAGE_SIZE >= 0 else None,
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


@router.post("/candidates/{candidate_id}/approve", dependencies=[require_admin])
async def candidate_approve(
    request: Request,
    candidate_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    redirect_to: str = Form(default="/admin/candidates"),
    session: AsyncSession = Depends(get_db_session),
):
    target = safe_redirect_target(redirect_to, "/admin/candidates")
    if not check_csrf(request, csrf_token):
        return redirect(target, err="Session expired")
    try:
        await schedule_moderation.approve_candidate(session, candidate_id, actor=ADMIN_ACTOR)
        await session.commit()
    except ValueError as exc:
        return redirect(target, err=str(exc))
    return redirect(target, msg="Candidate approved")


@router.post("/candidates/{candidate_id}/reject", dependencies=[require_admin])
async def candidate_reject(
    request: Request,
    candidate_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    reason: str | None = Form(default=None),
    redirect_to: str = Form(default="/admin/candidates"),
    session: AsyncSession = Depends(get_db_session),
):
    target = safe_redirect_target(redirect_to, "/admin/candidates")
    if not check_csrf(request, csrf_token):
        return redirect(target, err="Session expired")
    try:
        await schedule_moderation.reject_candidate(
            session, candidate_id, actor=ADMIN_ACTOR, reason=clean(reason)
        )
        await session.commit()
    except ValueError as exc:
        return redirect(target, err=str(exc))
    return redirect(target, msg="Candidate rejected")


def _make_schedule_trigger(task: object, ok_msg: str):
    async def _handler(request: Request, csrf_token: str = Form(default="")):
        return trigger_task(
            request,
            csrf_token,
            task=task,
            ok_msg=ok_msg,
            redirect_to="/admin/candidates",
        )

    return _handler


for _slug, (_task, _ok_msg) in _SCHEDULE_TRIGGERS.items():
    router.add_api_route(
        f"/schedule/{_slug}",
        _make_schedule_trigger(_task, _ok_msg),
        methods=["POST"],
        dependencies=[require_admin],
    )
