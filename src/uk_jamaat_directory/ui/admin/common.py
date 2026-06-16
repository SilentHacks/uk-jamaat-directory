"""Shared helpers for the admin UI route modules.

Every admin route module imports its primitives from here so behaviour stays
consistent: ``no-store`` caching, flash-message redirects, CSRF checks, form
field cleaning, Celery dispatch, and local-only redirect validation.
"""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import quote_plus, urlsplit

from fastapi import Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from uk_jamaat_directory.ui import auth

ADMIN_ACTOR = "admin-ui"
PAGE_SIZE = 50
NO_STORE = "no-store"


def no_store(resp: HTMLResponse) -> HTMLResponse:
    """Stamp ``Cache-Control: no-store`` on an admin HTML response."""
    resp.headers["Cache-Control"] = NO_STORE
    return resp


def redirect(path: str, *, msg: str | None = None, err: str | None = None) -> RedirectResponse:
    """303 redirect carrying an optional flash ``msg``/``err`` query param.

    Flash text is URL-encoded here, so callers pass human-readable strings
    (``"Mosque created"``) rather than pre-escaped ones.
    """
    params = []
    if msg:
        params.append(f"msg={quote_plus(msg)}")
    if err:
        params.append(f"err={quote_plus(err)}")
    if params:
        path = f"{path}{'&' if '?' in path else '?'}{'&'.join(params)}"
    resp = RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)
    resp.headers["Cache-Control"] = NO_STORE
    return resp


def check_csrf(request: Request, token: str | None) -> bool:
    return auth.validate_csrf(request, token)


def safe_redirect_target(value: str | None, default: str) -> str:
    """Clamp a form-supplied ``redirect_to`` to a local ``/admin`` path.

    Blocks absolute URLs, scheme-relative ``//host`` targets, and backslash
    tricks so the field cannot be abused as an open redirect.
    """
    if not value or "\\" in value:
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/admin"):
        return default
    return value


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_float(value: str | None) -> float | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def enqueue(task_callable: object, *args: object) -> str | None:
    """Dispatch a Celery task; return an error string on failure, else None."""
    try:
        task_callable.delay(*args)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator as a flash
        return str(exc)
    return None


def trigger_task(
    request: Request,
    csrf_token: str,
    *,
    task: object,
    ok_msg: str,
    redirect_to: str,
    args: Sequence[object] = (),
) -> RedirectResponse:
    """CSRF-guard, enqueue ``task``, and redirect with a success/error flash."""
    if not check_csrf(request, csrf_token):
        return redirect(redirect_to, err="Session expired")
    err = enqueue(task, *args)
    return redirect(redirect_to, msg=None if err else ok_msg, err=err)


__all__ = [
    "ADMIN_ACTOR",
    "PAGE_SIZE",
    "check_csrf",
    "clean",
    "enqueue",
    "no_store",
    "parse_float",
    "redirect",
    "safe_redirect_target",
    "trigger_task",
]
