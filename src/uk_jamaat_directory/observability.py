from __future__ import annotations

import logging

from uk_jamaat_directory.config import Settings

logger = logging.getLogger("uk_jamaat_directory.observability")

_initialized = False


def init_sentry(settings: Settings) -> None:
    """Initialise Sentry if a DSN is configured; otherwise do nothing.

    The SDK is imported lazily so it stays entirely inert (and optional as a
    dependency at runtime) when SENTRY_DSN is unset. Safe to call more than once.
    """
    global _initialized
    if _initialized or not settings.sentry_dsn:
        return

    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - SDK is a declared dependency
        logger.warning("SENTRY_DSN set but sentry-sdk is not installed; skipping")
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment.value,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )
    _initialized = True
    logger.info("sentry_initialized", extra={"environment": settings.environment.value})
