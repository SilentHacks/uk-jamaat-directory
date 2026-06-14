from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from uk_jamaat_directory.api import rate_limit
from uk_jamaat_directory.api.cache import cache_control
from uk_jamaat_directory.config import Environment, Settings
from uk_jamaat_directory.main import create_app
from uk_jamaat_directory.observability import init_sentry


def _client(**overrides) -> TestClient:
    settings = Settings(allowed_hosts="testserver", **overrides)
    return TestClient(create_app(settings))


def test_global_rate_limit_blocks_burst_and_sets_retry_after() -> None:
    rate_limit._public_limiter.reset()
    client = _client(public_rate_limit=3, public_rate_window_seconds=60)

    for _ in range(3):
        assert client.get("/v1/openapi.json").status_code == 200

    blocked = client.get("/v1/openapi.json")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_global_rate_limit_exempts_health() -> None:
    rate_limit._public_limiter.reset()
    client = _client(public_rate_limit=1, public_rate_window_seconds=60)

    # Health is exempt, so repeated calls never trip the limiter.
    for _ in range(5):
        assert client.get("/v1/health").status_code == 200


def test_global_rate_limit_disabled_when_non_positive() -> None:
    rate_limit._public_limiter.reset()
    client = _client(public_rate_limit=0)

    for _ in range(20):
        assert client.get("/v1/openapi.json").status_code == 200


def test_cache_control_dependency_sets_header() -> None:
    app = FastAPI()

    @app.get("/cached", dependencies=[cache_control("public, max-age=60")])
    async def cached() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).get("/cached")
    assert response.headers["Cache-Control"] == "public, max-age=60"


def test_cors_defaults_to_wildcard() -> None:
    # Bypass any developer .env so we assert the code default.
    assert Settings(_env_file=None).cors_origins == ["*"]


def test_init_sentry_noop_without_dsn() -> None:
    # Must not raise and must not require the SDK when no DSN is configured.
    init_sentry(Settings(environment=Environment.PRODUCTION, sentry_dsn=None))
