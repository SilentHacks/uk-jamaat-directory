"""Admin UI: shared-key login + management, moderation, and pipeline controls.

State-changing routes require an authenticated session (``require_admin_session``)
and a valid CSRF token submitted with the form. Heavy pipeline operations are
dispatched to Celery rather than run inline in the request.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import CandidateStatus, MosqueStatus
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    SourceExtractorAssignment,
)
from uk_jamaat_directory.schemas.admin import (
    AdminMosqueCreate,
    AdminMosqueMerge,
    AdminMosqueUpdate,
    AdminSourceAttach,
    AdminSourceUpdate,
)
from uk_jamaat_directory.services import (
    admin_identity,
    admin_reporting,
    admin_sources,
    schedule_moderation,
)
from uk_jamaat_directory.services.errors import (
    MosqueNotFoundError,
    SourceNotFoundError,
)
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin", tags=["admin-ui"], include_in_schema=False)
ADMIN_ACTOR = "admin-ui"
PAGE_SIZE = 50

# No-store on every admin response (handled per-render below).
NO_STORE = "no-store"


def _no_store(resp: HTMLResponse) -> HTMLResponse:
    resp.headers["Cache-Control"] = NO_STORE
    return resp


def _redirect(path: str, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    params = []
    if msg:
        params.append(f"msg={msg}")
    if err:
        params.append(f"err={err}")
    if params:
        path = f"{path}{'&' if '?' in path else '?'}{'&'.join(params)}"
    resp = RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)
    resp.headers["Cache-Control"] = NO_STORE
    return resp


def _check_csrf(request: Request, token: str | None) -> bool:
    return auth.validate_csrf(request, token)


# --------------------------------------------------------------------------- auth


@router.get("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    if auth.is_authenticated(request):
        return _redirect("/admin")
    return _no_store(
        render(
            request,
            "admin/login.html",
            {
                "csrf_token": auth.issue_csrf_token(request),
                "configured": settings.admin_ui_enabled,
            },
        )
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    settings: Settings = Depends(get_settings),
):
    if not settings.admin_ui_enabled:
        return _no_store(
            render(
                request,
                "admin/login.html",
                {"configured": False, "csrf_token": auth.issue_csrf_token(request)},
                status_code=503,
            )
        )
    if not _check_csrf(request, csrf_token):
        return _no_store(
            render(
                request,
                "admin/login.html",
                {
                    "configured": True,
                    "csrf_token": auth.issue_csrf_token(request),
                    "error": "Session expired. Please try again.",
                },
                status_code=400,
            )
        )
    if not auth.login_attempt_allowed(request, settings):
        return _no_store(
            render(
                request,
                "admin/login.html",
                {
                    "configured": True,
                    "csrf_token": auth.issue_csrf_token(request),
                    "error": "Too many attempts. Please wait and try again.",
                },
                status_code=429,
            )
        )
    if not auth.verify_admin_key(key, settings):
        return _no_store(
            render(
                request,
                "admin/login.html",
                {
                    "configured": True,
                    "csrf_token": auth.issue_csrf_token(request),
                    "error": "Invalid admin key.",
                },
                status_code=401,
            )
        )
    auth.mark_authenticated(request)
    return _redirect("/admin", msg="Signed+in")


@router.post("/logout")
async def logout(request: Request):
    auth.clear_session(request)
    return _redirect("/admin/login")


# ---------------------------------------------------------------------- dashboard


@router.get("", response_class=HTMLResponse, dependencies=[Depends(auth.require_admin_session)])
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    coverage = await admin_reporting.build_admin_coverage(session)
    health_rows, _ = await admin_reporting.list_source_health(session, limit=10)
    published_mosques = int(
        (
            await session.execute(select(func.count(func.distinct(_published_mosque_id_col()))))
        ).scalar_one()
    )
    pct_published = (
        round(100 * published_mosques / coverage.active_mosque_count, 1)
        if coverage.active_mosque_count
        else 0.0
    )
    return _no_store(
        render(
            request,
            "admin/dashboard.html",
            {
                "coverage": coverage,
                "health_rows": health_rows,
                "published_mosques": published_mosques,
                "pct_published": pct_published,
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


def _published_mosque_id_col():
    from uk_jamaat_directory.models.core import ScheduleOccurrence

    return ScheduleOccurrence.mosque_id


# ------------------------------------------------------------------------ mosques


async def _list_admin_mosques(
    session: AsyncSession,
    *,
    q: str | None,
    status_filter: str | None,
    offset: int,
) -> tuple[list[Mosque], int]:
    filters = []
    if status_filter:
        filters.append(Mosque.status == MosqueStatus(status_filter))
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Mosque.name.ilike(pattern),
                Mosque.normalized_name.ilike(pattern),
                Mosque.postcode.ilike(pattern),
                Mosque.city.ilike(pattern),
            )
        )
    count_stmt = select(func.count()).select_from(Mosque)
    stmt = select(Mosque).order_by(Mosque.name.asc())
    if filters:
        count_stmt = count_stmt.where(*filters)
        stmt = stmt.where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())
    rows = list((await session.execute(stmt.offset(offset).limit(PAGE_SIZE))).scalars().all())
    return rows, total


@router.get(
    "/mosques", response_class=HTMLResponse, dependencies=[Depends(auth.require_admin_session)]
)
async def mosques_list(
    request: Request,
    q: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    rows, total = await _list_admin_mosques(
        session, q=q, status_filter=status_filter, offset=offset
    )
    return _no_store(
        render(
            request,
            "admin/mosques.html",
            {
                "mosques": rows,
                "total": total,
                "q": q or "",
                "status_filter": status_filter or "",
                "statuses": [s.value for s in MosqueStatus],
                "offset": offset,
                "page_size": PAGE_SIZE,
                "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < total else None,
                "prev_offset": offset - PAGE_SIZE if offset - PAGE_SIZE >= 0 else None,
            },
        )
    )


@router.get(
    "/mosques/new", response_class=HTMLResponse, dependencies=[Depends(auth.require_admin_session)]
)
async def mosque_new(request: Request) -> HTMLResponse:
    return _no_store(
        render(
            request,
            "admin/mosque_form.html",
            {
                "mosque": None,
                "statuses": [s.value for s in MosqueStatus],
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_float(value: str | None) -> float | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


@router.post("/mosques", dependencies=[Depends(auth.require_admin_session)])
async def mosque_create(
    request: Request,
    csrf_token: str = Form(default=""),
    name: str = Form(...),
    status_value: str = Form(default="active", alias="status"),
    address_line1: str | None = Form(default=None),
    address_line2: str | None = Form(default=None),
    city: str | None = Form(default=None),
    county: str | None = Form(default=None),
    postcode: str | None = Form(default=None),
    country: str = Form(default="GB"),
    website_url: str | None = Form(default=None),
    latitude: str | None = Form(default=None),
    longitude: str | None = Form(default=None),
    public_notes: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect("/admin/mosques/new", err="Session+expired")
    payload = AdminMosqueCreate(
        name=name.strip(),
        address_line1=_clean(address_line1),
        address_line2=_clean(address_line2),
        city=_clean(city),
        county=_clean(county),
        postcode=_clean(postcode),
        country=(country or "GB").strip()[:2].upper() or "GB",
        website_url=_clean(website_url),
        latitude=_parse_float(latitude),
        longitude=_parse_float(longitude),
        status=status_value,
        public_notes=_clean(public_notes),
    )
    mosque = await admin_identity.create_mosque(session, payload, actor=ADMIN_ACTOR)
    await session.commit()
    return _redirect(f"/admin/mosques/{mosque.id}", msg="Mosque+created")


@router.get(
    "/mosques/{mosque_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(auth.require_admin_session)],
)
async def mosque_detail(
    request: Request,
    mosque_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    mosque = await session.get(Mosque, mosque_id)
    if mosque is None:
        return _no_store(render(request, "admin/not_found.html", {}, status_code=404))
    sources, _ = await admin_sources.list_sources(session, mosque_id=mosque_id, limit=200)
    lat = lng = None
    from uk_jamaat_directory.services.mappers import _coordinates_from_location

    lat, lng = _coordinates_from_location(mosque.location)
    return _no_store(
        render(
            request,
            "admin/mosque_detail.html",
            {
                "mosque": mosque,
                "latitude": lat,
                "longitude": lng,
                "sources": sources,
                "statuses": [s.value for s in MosqueStatus],
                "policies": [
                    "public_redistribution_allowed",
                    "private_use_only",
                    "unknown",
                    "blocked",
                ],
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


@router.post("/mosques/{mosque_id}", dependencies=[Depends(auth.require_admin_session)])
async def mosque_update(
    request: Request,
    mosque_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    name: str | None = Form(default=None),
    status_value: str | None = Form(default=None, alias="status"),
    address_line1: str | None = Form(default=None),
    address_line2: str | None = Form(default=None),
    city: str | None = Form(default=None),
    county: str | None = Form(default=None),
    postcode: str | None = Form(default=None),
    country: str | None = Form(default=None),
    website_url: str | None = Form(default=None),
    latitude: str | None = Form(default=None),
    longitude: str | None = Form(default=None),
    public_notes: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(f"/admin/mosques/{mosque_id}", err="Session+expired")
    payload = AdminMosqueUpdate(
        name=_clean(name),
        address_line1=_clean(address_line1),
        address_line2=_clean(address_line2),
        city=_clean(city),
        county=_clean(county),
        postcode=_clean(postcode),
        country=_clean(country),
        website_url=_clean(website_url),
        latitude=_parse_float(latitude),
        longitude=_parse_float(longitude),
        status=_clean(status_value),
        public_notes=_clean(public_notes),
    )
    try:
        await admin_identity.update_mosque(session, mosque_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except MosqueNotFoundError:
        return _redirect("/admin/mosques", err="Mosque+not+found")
    return _redirect(f"/admin/mosques/{mosque_id}", msg="Saved")


@router.post("/mosques/{mosque_id}/merge", dependencies=[Depends(auth.require_admin_session)])
async def mosque_merge(
    request: Request,
    mosque_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    duplicate_mosque_id: str = Form(...),
    reason: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(f"/admin/mosques/{mosque_id}", err="Session+expired")
    try:
        payload = AdminMosqueMerge(
            duplicate_mosque_id=uuid.UUID(duplicate_mosque_id.strip()),
            reason=_clean(reason),
        )
    except ValueError:
        return _redirect(f"/admin/mosques/{mosque_id}", err="Invalid+duplicate+id")
    try:
        await admin_identity.merge_mosques(session, mosque_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except (MosqueNotFoundError, ValueError) as exc:
        return _redirect(f"/admin/mosques/{mosque_id}", err=str(exc).replace(" ", "+"))
    return _redirect(f"/admin/mosques/{mosque_id}", msg="Merged+duplicate")


@router.post("/mosques/{mosque_id}/sources", dependencies=[Depends(auth.require_admin_session)])
async def mosque_attach_source(
    request: Request,
    mosque_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    source_type: str = Form(...),
    external_id: str = Form(...),
    source_url: str | None = Form(default=None),
    display_name: str | None = Form(default=None),
    publication_policy: str = Form(default="unknown"),
    confidence: str = Form(default="community"),
    attribution: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(f"/admin/mosques/{mosque_id}", err="Session+expired")
    payload = AdminSourceAttach(
        source_type=source_type.strip(),
        external_id=external_id.strip(),
        source_url=_clean(source_url),
        display_name=_clean(display_name),
        publication_policy=publication_policy,
        confidence=confidence,
        attribution=_clean(attribution),
    )
    try:
        await admin_identity.attach_source(session, mosque_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except (MosqueNotFoundError, ValueError) as exc:
        return _redirect(f"/admin/mosques/{mosque_id}", err=str(exc).replace(" ", "+"))
    return _redirect(f"/admin/mosques/{mosque_id}", msg="Source+attached")


@router.post("/sources/{source_id}", dependencies=[Depends(auth.require_admin_session)])
async def source_update(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    publication_policy: str | None = Form(default=None),
    confidence: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    display_name: str | None = Form(default=None),
    attribution: str | None = Form(default=None),
    redirect_to: str = Form(default="/admin/mosques"),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(redirect_to, err="Session+expired")
    payload = AdminSourceUpdate(
        publication_policy=_clean(publication_policy),
        confidence=_clean(confidence),
        source_url=_clean(source_url),
        display_name=_clean(display_name),
        attribution=_clean(attribution),
    )
    try:
        await admin_sources.update_source(session, source_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except SourceNotFoundError:
        return _redirect(redirect_to, err="Source+not+found")
    return _redirect(redirect_to, msg="Source+updated")


# --------------------------------------------------------------------- moderation


@router.get(
    "/candidates", response_class=HTMLResponse, dependencies=[Depends(auth.require_admin_session)]
)
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
    return _no_store(
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


@router.post(
    "/candidates/{candidate_id}/approve", dependencies=[Depends(auth.require_admin_session)]
)
async def candidate_approve(
    request: Request,
    candidate_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    redirect_to: str = Form(default="/admin/candidates"),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(redirect_to, err="Session+expired")
    try:
        await schedule_moderation.approve_candidate(session, candidate_id, actor=ADMIN_ACTOR)
        await session.commit()
    except ValueError as exc:
        return _redirect(redirect_to, err=str(exc).replace(" ", "+"))
    return _redirect(redirect_to, msg="Candidate+approved")


@router.post(
    "/candidates/{candidate_id}/reject", dependencies=[Depends(auth.require_admin_session)]
)
async def candidate_reject(
    request: Request,
    candidate_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    reason: str | None = Form(default=None),
    redirect_to: str = Form(default="/admin/candidates"),
    session: AsyncSession = Depends(get_db_session),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(redirect_to, err="Session+expired")
    try:
        await schedule_moderation.reject_candidate(
            session, candidate_id, actor=ADMIN_ACTOR, reason=_clean(reason)
        )
        await session.commit()
    except ValueError as exc:
        return _redirect(redirect_to, err=str(exc).replace(" ", "+"))
    return _redirect(redirect_to, msg="Candidate+rejected")


def _enqueue(task_callable, *args) -> str | None:
    """Dispatch a Celery task; return an error string on failure, else None."""
    try:
        task_callable.delay(*args)
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator as a flash
        return str(exc).replace(" ", "+")
    return None


@router.post("/schedule/validate", dependencies=[Depends(auth.require_admin_session)])
async def schedule_validate(request: Request, csrf_token: str = Form(default="")):
    if not _check_csrf(request, csrf_token):
        return _redirect("/admin/candidates", err="Session+expired")
    from uk_jamaat_directory.tasks.schedules import validate_candidates_task

    err = _enqueue(validate_candidates_task)
    return (
        _redirect("/admin/candidates", err=err)
        if err
        else _redirect("/admin/candidates", msg="Validation+queued")
    )


@router.post("/schedule/publish", dependencies=[Depends(auth.require_admin_session)])
async def schedule_publish(request: Request, csrf_token: str = Form(default="")):
    if not _check_csrf(request, csrf_token):
        return _redirect("/admin/candidates", err="Session+expired")
    from uk_jamaat_directory.tasks.schedules import publish_candidates_task

    err = _enqueue(publish_candidates_task)
    return (
        _redirect("/admin/candidates", err=err)
        if err
        else _redirect("/admin/candidates", msg="Publish+queued")
    )


@router.post("/schedule/recompute-freshness", dependencies=[Depends(auth.require_admin_session)])
async def schedule_recompute(request: Request, csrf_token: str = Form(default="")):
    if not _check_csrf(request, csrf_token):
        return _redirect("/admin/candidates", err="Session+expired")
    from uk_jamaat_directory.tasks.schedules import recompute_freshness_task

    err = _enqueue(recompute_freshness_task)
    return (
        _redirect("/admin/candidates", err=err)
        if err
        else _redirect("/admin/candidates", msg="Freshness+recompute+queued")
    )


# ----------------------------------------------------------------------- pipeline


@router.get(
    "/pipeline", response_class=HTMLResponse, dependencies=[Depends(auth.require_admin_session)]
)
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
    return _no_store(
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


@router.post("/sources/{source_id}/crawl", dependencies=[Depends(auth.require_admin_session)])
async def source_crawl(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    redirect_to: str = Form(default="/admin/pipeline"),
):
    if not _check_csrf(request, csrf_token):
        return _redirect(redirect_to, err="Session+expired")
    from uk_jamaat_directory.tasks.crawl import process_source_task

    err = _enqueue(process_source_task, str(source_id))
    return _redirect(redirect_to, err=err) if err else _redirect(redirect_to, msg="Crawl+queued")
