from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any

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

    database_url: str = "postgresql+asyncpg://directory:directory@localhost:54324/directory"
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
    # Documented operator intent; production VPS enforces proxy headers via
    # uvicorn --proxy-headers in docker-compose.production.yml, not app middleware.
    trust_proxy_headers: bool = False

    mylocalmasjid_enabled: bool = False
    mylocalmasjid_publication_policy: str = "unknown"
    muslimsinbritain_enabled: bool = False
    muslimsinbritain_publication_policy: str = "public_redistribution_allowed"
    openai_api_key: str | None = None

    community_submission_rate_limit: int = 10
    community_submission_rate_window_seconds: int = 60

    schedule_date_past_days: int = 7
    schedule_date_future_days: int = 400
    freshness_stale_days: int = 30
    source_last_seen_stale_days: int = 30
    mlm_report_stale_days: int = 7
    mib_report_stale_days: int = 30
    publish_allow_ai: bool = False

    crawl_enabled: bool = False
    crawl_user_agent: str = (
        "UKJamaatDirectoryBot/0.1 (+https://github.com/SilentHacks/uk-jamaat-directory)"
    )
    crawl_timeout_seconds: float = 20.0
    crawl_max_bytes: int = 5_000_000
    crawl_per_domain_delay_seconds: float = 2.0
    crawl_interval_hours: int = 24
    crawl_validate_after_extract: bool = True

    repo_extractor_timeout_seconds: float = 30.0
    repo_extractor_ocr_timeout_seconds: float = 120.0
    repo_extractor_auto_approve_candidates: bool = True

    ai_agent_model: str = "opencode-go/deepseek-v4-flash"
    ai_agent_base_url: str | None = None
    ai_agent_api_key: str | None = None
    authoring_concurrency: int = 8
    authoring_per_source_timeout_seconds: float = 180.0
    authoring_global_timeout_seconds: float = 4 * 60 * 60.0
    authoring_drafts_dir: str = "data/authoring/drafts"
    authoring_max_candidate_links: int = 5
    authoring_max_sample_bytes: int = 16_000
    authoring_keyword_boost: float = 2.0

    osm_overpass_url: str = "https://overpass-api.de/api/interpreter"
    osm_overpass_timeout_seconds: float = 180.0

    exa_search_api_key: str | None = None
    search_engine_max_concurrency: int = 8

    export_base_url: str | None = None
    export_s3_prefix: str = "exports"
    export_enabled: bool = False

    @property
    def export_public_base_url(self) -> str:
        return self.export_base_url or self.public_base_url

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
