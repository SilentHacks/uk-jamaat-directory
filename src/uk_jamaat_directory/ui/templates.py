"""Jinja2 environment and shared template helpers for the SSR UI."""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

#: Prayer display order used by the public timetable grid.
PRAYER_ORDER = ("fajr", "dhuhr", "asr", "maghrib", "isha", "jumuah")

PRAYER_LABELS = {
    "fajr": "Fajr",
    "dhuhr": "Dhuhr",
    "asr": "Asr",
    "maghrib": "Maghrib",
    "isha": "Isha",
    "jumuah": "Jumu'ah",
}

#: Confidence values that mean the time was computed, not a published jamaat.
CALCULATED_CONFIDENCES = {"calculated"}


def _format_time(value: time | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%H:%M")


def _format_date(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%a %d %b")


def _prayer_label(value: str) -> str:
    return PRAYER_LABELS.get(value, value.title())


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters["fmt_time"] = _format_time
templates.env.filters["fmt_date"] = _format_date
templates.env.filters["prayer_label"] = _prayer_label
templates.env.globals["prayer_order"] = PRAYER_ORDER
templates.env.globals["calculated_confidences"] = CALCULATED_CONFIDENCES


def render(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
):
    """Render a template with the shared request context."""
    ctx: dict[str, Any] = {"request": request}
    # Expose auth state to the shared layout (nav shows the Admin link when set).
    try:
        ctx["admin_authenticated"] = bool(request.session.get("admin_authenticated"))
    except (AssertionError, KeyError):
        ctx["admin_authenticated"] = False
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, template_name, ctx, status_code=status_code)
