from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from uk_jamaat_directory.api.errors import install_exception_handlers
from uk_jamaat_directory.api.v1.router import api_router
from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.logging import configure_logging
from uk_jamaat_directory.middleware import request_context_middleware


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        openapi_url=resolved_settings.openapi_url,
        docs_url=resolved_settings.docs_url,
        redoc_url=resolved_settings.redoc_url,
    )
    install_exception_handlers(app)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Request-ID"],
    )
    app.middleware("http")(request_context_middleware)
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    app.dependency_overrides[get_settings] = lambda: resolved_settings
    return app


app = create_app()
