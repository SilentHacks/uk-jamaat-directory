"""Admin UI authentication: shared-key login over a signed session cookie.

The JSON admin API (``/v1/admin``) keeps its ``X-Admin-Key`` header contract for
programmatic use. The browser-facing admin UI instead authenticates once via a
login form and carries a signed session cookie, with a CSRF token guarding every
state-changing POST.
"""

from __future__ import annotations

import secrets
from hmac import compare_digest

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from uk_jamaat_directory.api.rate_limit import SlidingWindowLimiter
from uk_jamaat_directory.config import Settings, get_settings

_SESSION_AUTH_KEY = "admin_authenticated"
_SESSION_CSRF_KEY = "csrf_token"
_login_limiter = SlidingWindowLimiter()


def _client_key(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def login_attempt_allowed(request: Request, settings: Settings) -> bool:
    return _login_limiter.check(
        _client_key(request),
        settings.admin_login_rate_limit,
        settings.admin_login_rate_window_seconds,
    )


def verify_admin_key(provided: str, settings: Settings) -> bool:
    if not settings.admin_api_key:
        return False
    return compare_digest(provided, settings.admin_api_key)


def issue_csrf_token(request: Request) -> str:
    token = request.session.get(_SESSION_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_CSRF_KEY] = token
    return token


def validate_csrf(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(_SESSION_CSRF_KEY)
    if not expected or not submitted:
        return False
    return compare_digest(submitted, expected)


def mark_authenticated(request: Request) -> None:
    request.session[_SESSION_AUTH_KEY] = True
    # Rotate the CSRF token on privilege change.
    request.session[_SESSION_CSRF_KEY] = secrets.token_urlsafe(32)


def clear_session(request: Request) -> None:
    request.session.clear()


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get(_SESSION_AUTH_KEY))


class RedirectToLogin(HTTPException):
    """Signals that an unauthenticated user hit a protected admin route."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_303_SEE_OTHER, detail="login required")


async def require_admin_session(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Guard admin UI routes; redirect anonymous users to the login page."""
    if not settings.admin_ui_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin UI is not configured",
        )
    if not is_authenticated(request):
        raise RedirectToLogin()


def login_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
