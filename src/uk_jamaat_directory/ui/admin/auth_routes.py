"""Admin UI authentication routes: login form, login submit, logout."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ui import auth
from uk_jamaat_directory.ui.admin.common import no_store, redirect
from uk_jamaat_directory.ui.templates import render

router = APIRouter(prefix="/admin")


def _login_page(
    request: Request,
    *,
    configured: bool,
    status_code: int = 200,
    error: str | None = None,
) -> HTMLResponse:
    context = {
        "configured": configured,
        "csrf_token": auth.issue_csrf_token(request),
    }
    if error is not None:
        context["error"] = error
    return no_store(render(request, "admin/login.html", context, status_code=status_code))


@router.get("/login", response_class=HTMLResponse)
async def login_form(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    if auth.is_authenticated(request):
        return redirect("/admin")
    return _login_page(request, configured=settings.admin_ui_enabled)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    key: str = Form(default=""),
    csrf_token: str = Form(default=""),
    settings: Settings = Depends(get_settings),
):
    if not settings.admin_ui_enabled:
        return _login_page(request, configured=False, status_code=503)
    if not auth.validate_csrf(request, csrf_token):
        return _login_page(
            request,
            configured=True,
            status_code=400,
            error="Session expired. Please try again.",
        )
    if not auth.login_attempt_allowed(request, settings):
        return _login_page(
            request,
            configured=True,
            status_code=429,
            error="Too many attempts. Please wait and try again.",
        )
    if not auth.verify_admin_key(key, settings):
        return _login_page(
            request,
            configured=True,
            status_code=401,
            error="Invalid admin key.",
        )
    auth.mark_authenticated(request)
    return redirect("/admin", msg="Signed in")


@router.post("/logout")
async def logout(request: Request):
    auth.clear_session(request)
    return redirect("/admin/login")
