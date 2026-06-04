from __future__ import annotations

from fastapi import FastAPI

from uk_jamaat_directory.api.v1.router import api_router
from uk_jamaat_directory.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        openapi_url=resolved_settings.openapi_url,
        docs_url=resolved_settings.docs_url,
        redoc_url=resolved_settings.redoc_url,
    )
    app.include_router(api_router, prefix=resolved_settings.api_prefix)
    return app


app = create_app()
