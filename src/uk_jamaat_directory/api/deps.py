from __future__ import annotations

from hmac import compare_digest

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from uk_jamaat_directory.config import Settings, get_settings

admin_api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def require_admin_key(
    provided_key: str | None = Depends(admin_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is not configured",
        )

    if not provided_key or not compare_digest(provided_key, settings.admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin API key",
        )
