from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from uk_jamaat_directory.api.errors import install_exception_handlers
from uk_jamaat_directory.api.openapi_public import build_public_openapi
from uk_jamaat_directory.api.rate_limit import public_rate_limit_middleware
from uk_jamaat_directory.api.v1.router import api_router
from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.logging import configure_logging
from uk_jamaat_directory.middleware import request_context_middleware
from uk_jamaat_directory.observability import init_sentry


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
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    _register_docs(app, resolved_settings)
    app.dependency_overrides[get_settings] = lambda: resolved_settings
    return app


app = create_app()
