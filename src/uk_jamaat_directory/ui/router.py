"""Public-facing dashboard routes: search/browse mosques and view timetables."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.services import public_reads
from uk_jamaat_directory.ui.templates import PRAYER_ORDER, render

router = APIRouter(tags=["ui"], include_in_schema=False)

# Browser pages are cheap to regenerate; allow a short shared cache.
PAGE_CACHE = "public, max-age=60"
PAGE_SIZE = 25


def _monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


async def _search_results(
    session: AsyncSession,
    *,
    q: str | None,
    city: str | None,
    postcode: str | None,
    crawled: bool,
    offset: int,
):
    """Run a list/search query and return (response, has_more, next_offset)."""
    has_query = any(v and v.strip() for v in (q, city, postcode))
    if has_query:
        result = await public_reads.search_mosques(
            session,
            query=q,
            postcode=postcode,
            city=city,
            limit=PAGE_SIZE + 1,
            crawled_only=crawled,
        )
    else:
        result = await public_reads.list_mosques(
            session,
            limit=PAGE_SIZE + 1,
            offset=offset,
            city=city,
            postcode=postcode,
            crawled_only=crawled,
        )
    items = list(result.items)
    has_more = len(items) > PAGE_SIZE
    items = items[:PAGE_SIZE]
    # search_mosques does not paginate; only the unfiltered listing pages.
    next_offset = offset + PAGE_SIZE if (has_more and not has_query) else None
    return items, result.count, next_offset


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(
    request: Request,
    q: str | None = Query(default=None),
    city: str | None = Query(default=None),
    postcode: str | None = Query(default=None),
    crawled: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    items, total, next_offset = await _search_results(
        session, q=q, city=city, postcode=postcode, crawled=crawled, offset=0
    )
    resp = render(
        request,
        "public/index.html",
        {
            "items": items,
            "total": total,
            "q": q or "",
            "city": city or "",
            "postcode": postcode or "",
            "crawled": crawled,
            "next_offset": next_offset,
        },
    )
    resp.headers["Cache-Control"] = PAGE_CACHE
    return resp


@router.get("/partials/mosques", response_class=HTMLResponse)
async def mosque_results(
    request: Request,
    q: str | None = Query(default=None),
    city: str | None = Query(default=None),
    postcode: str | None = Query(default=None),
    crawled: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    items, total, next_offset = await _search_results(
        session, q=q, city=city, postcode=postcode, crawled=crawled, offset=offset
    )
    return render(
        request,
        "public/_results.html",
        {
            "items": items,
            "total": total,
            "q": q or "",
            "city": city or "",
            "postcode": postcode or "",
            "crawled": crawled,
            "next_offset": next_offset,
            "append": offset > 0,
        },
    )


@router.api_route(
    "/mosques/{mosque_id}", methods=["GET", "HEAD"], response_class=HTMLResponse
)
async def mosque_detail(
    request: Request,
    mosque_id: uuid.UUID,
    week: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    mosque = await public_reads.get_mosque(session, mosque_id)
    if mosque is None:
        return render(request, "public/not_found.html", {}, status_code=404)

    week_start = _monday(week or date.today())
    grid = await _timetable_grid(session, mosque_id, week_start)
    resp = render(
        request,
        "public/mosque_detail.html",
        {"mosque": mosque, **grid},
    )
    resp.headers["Cache-Control"] = PAGE_CACHE
    return resp


@router.get("/partials/mosques/{mosque_id}/timetable", response_class=HTMLResponse)
async def mosque_timetable(
    request: Request,
    mosque_id: uuid.UUID,
    week: date | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    week_start = _monday(week or date.today())
    grid = await _timetable_grid(session, mosque_id, week_start)
    return render(request, "public/_timetable.html", grid)


async def _timetable_grid(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    week_start: date,
) -> dict:
    """Build a prayer x day grid for the week starting on ``week_start``."""
    week_end = week_start + timedelta(days=6)
    times = await public_reads.get_mosque_times(
        session, mosque_id, from_date=week_start, to_date=week_end
    )
    days = [week_start + timedelta(days=i) for i in range(7)]
    # grid[prayer][iso_date] -> list of occurrences (multiple sessions possible).
    grid: dict[str, dict[str, list]] = {p: {d.isoformat(): [] for d in days} for p in PRAYER_ORDER}
    has_any = False
    if times is not None:
        for occ in times.items:
            bucket = grid.get(occ.prayer)
            if bucket is None:
                continue
            key = occ.date.isoformat()
            if key in bucket:
                bucket[key].append(occ)
                has_any = True
    return {
        "mosque_id": mosque_id,
        "days": days,
        "grid": grid,
        "week_start": week_start,
        "prev_week": week_start - timedelta(days=7),
        "next_week": week_start + timedelta(days=7),
        "has_any": has_any,
    }


@router.api_route("/about", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def about(request: Request) -> HTMLResponse:
    resp = render(request, "public/about.html", {})
    resp.headers["Cache-Control"] = PAGE_CACHE
    return resp
