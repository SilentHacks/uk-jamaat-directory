from __future__ import annotations

import pytest

from uk_jamaat_directory.config import Environment, Settings


def test_csv_environment_lists_are_parsed() -> None:
    settings = Settings(
        allowed_hosts="directory.example.org,localhost",
        cors_origins="https://directory.example.org,http://localhost:3000",
    )

    assert settings.allowed_hosts == ["directory.example.org", "localhost"]
    assert settings.cors_origins == ["https://directory.example.org", "http://localhost:3000"]


def test_api_prefix_must_start_with_slash() -> None:
    with pytest.raises(ValueError, match="api_prefix"):
        Settings(api_prefix="v1")


def test_public_openapi_url_follows_prefix() -> None:
    assert Settings().public_openapi_url == "/v1/openapi.json"
    assert Settings(api_prefix="/api").public_openapi_url == "/api/openapi.json"


def test_internal_docs_default_off_in_production_only() -> None:
    assert Settings(environment=Environment.DEVELOPMENT).internal_docs_active is True
    assert Settings(environment=Environment.PRODUCTION).internal_docs_active is False
    # Explicit override wins over the environment default.
    assert (
        Settings(
            environment=Environment.PRODUCTION, internal_docs_enabled=True
        ).internal_docs_active
        is True
    )
