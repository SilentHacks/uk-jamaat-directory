from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Any

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "UK Jamaat Directory"
    app_version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    api_prefix: str = "/v1"
    public_base_url: str = "http://localhost:8000"
    docs_enabled: bool = True
    admin_api_key: str | None = None

    database_url: str = "postgresql+asyncpg://directory:directory@localhost:5432/directory"
    test_database_url: str | None = None

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "uk-jamaat-directory-local"
    s3_access_key_id: str = "directory"
    s3_secret_access_key: str = "directory-secret"

    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:8000"]
    )
    trust_proxy_headers: bool = False

    mylocalmasjid_enabled: bool = False
    mylocalmasjid_publication_policy: str = "unknown"
    openai_api_key: str | None = None

    community_submission_rate_limit: int = 10
    community_submission_rate_window_seconds: int = 60

    @field_validator("api_prefix")
    @classmethod
    def api_prefix_must_start_with_slash(cls, value: str) -> str:
        if not value.startswith("/"):
            msg = "api_prefix must start with '/'"
            raise ValueError(msg)
        return value.rstrip("/") or "/"

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def parse_csv_list(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def openapi_url(self) -> str | None:
        if self.docs_enabled and self.environment != Environment.PRODUCTION:
            return f"{self.api_prefix}/openapi.json"
        return None

    @property
    def docs_url(self) -> str | None:
        if self.docs_enabled and self.environment != Environment.PRODUCTION:
            return "/docs"
        return None

    @property
    def redoc_url(self) -> str | None:
        if self.docs_enabled and self.environment != Environment.PRODUCTION:
            return "/redoc"
        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
