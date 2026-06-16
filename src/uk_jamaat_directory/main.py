from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from uk_jamaat_directory.api.errors import install_exception_handlers
from uk_jamaat_directory.api.openapi_public import build_public_openapi
from uk_jamaat_directory.api.rate_limit import public_rate_limit_middleware
from uk_jamaat_directory.api.v1.router import api_router
from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.logging import configure_logging
from uk_jamaat_directory.middleware import request_context_middleware
from uk_jamaat_directory.observability import init_sentry
from uk_jamaat_directory.ui.admin import router as admin_ui_router
from uk_jamaat_directory.ui.router import router as ui_router


def _register_docs(app: FastAPI, settings: Settings) -> None:
    """Wire OpenAPI/docs routes explicitly so the app stays a pure JSON API.

    The public spec is filtered (admin routes excluded) and served in every
    environment. The full spec and Swagger UI live under /internal and default
    to off in production.
    """
    if settings.public_openapi_enabled:

        @app.get(settings.public_openapi_url, include_in_schema=False)
        async def public_openapi() -> JSONResponse:
            cached = getattr(app.state, "public_openapi_spec", None)
            if cached is None:
                cached = build_public_openapi(app)
                app.state.public_openapi_spec = cached
            return JSONResponse(cached)

    if settings.internal_docs_active:

        @app.get("/internal/openapi.json", include_in_schema=False)
        async def internal_openapi() -> JSONResponse:
            cached = getattr(app.state, "internal_openapi_spec", None)
            if cached is None:
                cached = get_openapi(title=app.title, version=app.version, routes=app.routes)
                app.state.internal_openapi_spec = cached
            return JSONResponse(cached)

        @app.get("/internal/docs", include_in_schema=False)
        async def internal_docs() -> Any:
            return get_swagger_ui_html(
                openapi_url="/internal/openapi.json",
                title=f"{app.title} — internal API",
            )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging()
    init_sentry(resolved_settings)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = resolved_settings
    install_exception_handlers(app)
    _install_admin_redirect(app)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Request-ID"],
    )
    # Added last = outermost: request context (IDs, logging) wraps the rate limiter
    # so even 429 responses get an X-Request-ID and a log line.
    app.middleware("http")(public_rate_limit_middleware)
    app.middleware("http")(request_context_middleware)
    # Signed session cookie for the admin UI login. When no secret is configured
    # the admin UI login simply rejects every attempt (see ui.auth), but the
    # middleware still needs *a* key to run; use an ephemeral one in that case.
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved_settings.session_secret_key or "ujd-insecure-dev-session-key",
        session_cookie=resolved_settings.session_cookie_name,
        max_age=resolved_settings.session_max_age_seconds,
        same_site="lax",
        https_only=resolved_settings.session_https_only,
    )
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    app.include_router(ui_router)
    app.include_router(admin_ui_router)
    _register_docs(app, resolved_settings)
    _mount_dev_static(app)
    app.dependency_overrides[get_settings] = lambda: resolved_settings
    return app


def _install_admin_redirect(app: FastAPI) -> None:
    """Turn the admin-session redirect signal into an HTTP redirect response."""
    from starlette.responses import RedirectResponse

    from uk_jamaat_directory.ui.auth import RedirectToLogin

    async def _redirect_handler(request: Any, exc: RedirectToLogin):  # noqa: ARG001
        return RedirectResponse(url="/admin/login", status_code=303)

    app.add_exception_handler(RedirectToLogin, _redirect_handler)


def _mount_dev_static(app: FastAPI) -> None:
    """Serve /assets locally when running uvicorn without Caddy.

    In production Caddy serves /assets from ``web/public`` before requests reach
    the app, so this mount is only exercised by ``make dev``. It is skipped when
    the directory is absent (e.g. inside the API container image).
    """
    assets_dir = Path(__file__).resolve().parents[2] / "web" / "public" / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


app = create_app()
