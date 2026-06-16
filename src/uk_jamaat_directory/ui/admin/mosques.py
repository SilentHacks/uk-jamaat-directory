"""Admin UI mosque management: list, create, edit, merge, source policy."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.domain import MosqueStatus
from uk_jamaat_directory.models.core import Mosque
from uk_jamaat_directory.schemas.admin import (
    AdminMosqueCreate,
    AdminMosqueMerge,
    AdminMosqueUpdate,
    AdminSourceAttach,
    AdminSourceUpdate,
)
from uk_jamaat_directory.services import admin_identity, admin_sources
from uk_jamaat_directory.services.errors import MosqueNotFoundError, SourceNotFoundError
from uk_jamaat_directory.services.mappers import coordinates_from_location
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.admin.common import (
    ADMIN_ACTOR,
    PAGE_SIZE,
    check_csrf,
    clean,
    no_store,
    parse_float,
    redirect,
    safe_redirect_target,
)
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin")

SOURCE_POLICIES = (
    "public_redistribution_allowed",
    "private_use_only",
    "unknown",
    "blocked",
)
require_admin = Depends(auth.require_admin_session)


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


@router.get("/mosques", response_class=HTMLResponse, dependencies=[require_admin])
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
    return no_store(
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


@router.get("/mosques/new", response_class=HTMLResponse, dependencies=[require_admin])
async def mosque_new(request: Request) -> HTMLResponse:
    return no_store(
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


@router.post("/mosques", dependencies=[require_admin])
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
    if not check_csrf(request, csrf_token):
        return redirect("/admin/mosques/new", err="Session expired")
    payload = AdminMosqueCreate(
        name=name.strip(),
        address_line1=clean(address_line1),
        address_line2=clean(address_line2),
        city=clean(city),
        county=clean(county),
        postcode=clean(postcode),
        country=(country or "GB").strip()[:2].upper() or "GB",
        website_url=clean(website_url),
        latitude=parse_float(latitude),
        longitude=parse_float(longitude),
        status=status_value,
        public_notes=clean(public_notes),
    )
    mosque = await admin_identity.create_mosque(session, payload, actor=ADMIN_ACTOR)
    await session.commit()
    return redirect(f"/admin/mosques/{mosque.id}", msg="Mosque created")


@router.get("/mosques/{mosque_id}", response_class=HTMLResponse, dependencies=[require_admin])
async def mosque_detail(
    request: Request,
    mosque_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    mosque = await session.get(Mosque, mosque_id)
    if mosque is None:
        return no_store(render(request, "admin/not_found.html", {}, status_code=404))
    sources, _ = await admin_sources.list_sources(session, mosque_id=mosque_id, limit=200)
    lat, lng = coordinates_from_location(mosque.location)
    return no_store(
        render(
            request,
            "admin/mosque_detail.html",
            {
                "mosque": mosque,
                "latitude": lat,
                "longitude": lng,
                "sources": sources,
                "statuses": [s.value for s in MosqueStatus],
                "policies": list(SOURCE_POLICIES),
                "csrf_token": auth.issue_csrf_token(request),
            },
        )
    )


@router.post("/mosques/{mosque_id}", dependencies=[require_admin])
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
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/mosques/{mosque_id}", err="Session expired")
    payload = AdminMosqueUpdate(
        name=clean(name),
        address_line1=clean(address_line1),
        address_line2=clean(address_line2),
        city=clean(city),
        county=clean(county),
        postcode=clean(postcode),
        country=clean(country),
        website_url=clean(website_url),
        latitude=parse_float(latitude),
        longitude=parse_float(longitude),
        status=clean(status_value),
        public_notes=clean(public_notes),
    )
    try:
        await admin_identity.update_mosque(session, mosque_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except MosqueNotFoundError:
        return redirect("/admin/mosques", err="Mosque not found")
    return redirect(f"/admin/mosques/{mosque_id}", msg="Saved")


@router.post("/mosques/{mosque_id}/merge", dependencies=[require_admin])
async def mosque_merge(
    request: Request,
    mosque_id: uuid.UUID,
    csrf_token: str = Form(default=""),
    duplicate_mosque_id: str = Form(...),
    reason: str | None = Form(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/mosques/{mosque_id}", err="Session expired")
    try:
        payload = AdminMosqueMerge(
            duplicate_mosque_id=uuid.UUID(duplicate_mosque_id.strip()),
            reason=clean(reason),
        )
    except ValueError:
        return redirect(f"/admin/mosques/{mosque_id}", err="Invalid duplicate id")
    try:
        await admin_identity.merge_mosques(session, mosque_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except (MosqueNotFoundError, ValueError) as exc:
        return redirect(f"/admin/mosques/{mosque_id}", err=str(exc))
    return redirect(f"/admin/mosques/{mosque_id}", msg="Merged duplicate")


@router.post("/mosques/{mosque_id}/sources", dependencies=[require_admin])
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
    if not check_csrf(request, csrf_token):
        return redirect(f"/admin/mosques/{mosque_id}", err="Session expired")
    payload = AdminSourceAttach(
        source_type=source_type.strip(),
        external_id=external_id.strip(),
        source_url=clean(source_url),
        display_name=clean(display_name),
        publication_policy=publication_policy,
        confidence=confidence,
        attribution=clean(attribution),
    )
    try:
        await admin_identity.attach_source(session, mosque_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except (MosqueNotFoundError, ValueError) as exc:
        return redirect(f"/admin/mosques/{mosque_id}", err=str(exc))
    return redirect(f"/admin/mosques/{mosque_id}", msg="Source attached")


@router.post("/sources/{source_id}", dependencies=[require_admin])
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
    target = safe_redirect_target(redirect_to, "/admin/mosques")
    if not check_csrf(request, csrf_token):
        return redirect(target, err="Session expired")
    payload = AdminSourceUpdate(
        publication_policy=clean(publication_policy),
        confidence=clean(confidence),
        source_url=clean(source_url),
        display_name=clean(display_name),
        attribution=clean(attribution),
    )
    try:
        await admin_sources.update_source(session, source_id, payload, actor=ADMIN_ACTOR)
        await session.commit()
    except SourceNotFoundError:
        return redirect(target, err="Source not found")
    return redirect(target, msg="Source updated")
