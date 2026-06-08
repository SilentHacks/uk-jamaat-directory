from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from uk_jamaat_directory.domain import Prayer

TARGET_KINDS = ("html", "pdf", "image", "json", "rendered_html")
SUPPORTED_FREQUENCIES = (
    "hourly",
    "daily",
    "weekly",
    "monthly",
    "ramadan_daily",
    "manual",
)


class TargetKind(StrEnum):
    HTML = "html"
    PDF = "pdf"
    IMAGE = "image"
    JSON = "json"
    RENDERED_HTML = "rendered_html"


class RunFrequency(StrEnum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    RAMADAN_DAILY = "ramadan_daily"
    MANUAL = "manual"


class SourceMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domains: tuple[str, ...] = Field(default_factory=tuple)
    mosque_name_patterns: tuple[str, ...] = Field(default_factory=tuple)
    path_patterns: tuple[str, ...] = Field(default_factory=tuple)

    def matches(self, *, domain: str | None, name: str | None) -> bool:
        if self.domains:
            if not domain:
                return False
            normalized = domain.lower()
            if not any(
                normalized == candidate.lower() or normalized.endswith(f".{candidate.lower()}")
                for candidate in self.domains
            ):
                return False
        if self.mosque_name_patterns and name:
            lowered = name.lower()
            if not any(pattern.lower() in lowered for pattern in self.mosque_name_patterns):
                return False
        return True


class TargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    url: str
    kind: TargetKind
    path: str | None = None
    requires_javascript: bool = False
    requires_pdf: bool = False
    requires_ocr: bool = False

    @field_validator("label")
    @classmethod
    def _label_present(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "target label is required"
            raise ValueError(msg)
        return cleaned

    @field_validator("url")
    @classmethod
    def _url_present(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            msg = "target url is required"
            raise ValueError(msg)
        return cleaned


class RefreshPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency: RunFrequency
    timezone: str = "Europe/London"

    @field_validator("frequency", mode="before")
    @classmethod
    def _coerce_frequency(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value


class ExtractorArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_label: str
    target_url: str
    content_type: str | None = None
    body: bytes
    content_hash: str | None = None

    def text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        return self.body.decode(encoding, errors=errors)


class ExtractorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_label: str
    target_url: str
    artifact_id: str | None = None
    extractor_key: str
    extractor_version: str
    contract: str = "repo_site_extractor/v1"
    gate_passed: bool = True
    raw_text: str | None = None
    selector: str | None = None
    derivation: dict[str, Any] | None = None
    notes: str | None = None


class ExtractorRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date
    prayer: Prayer
    jamaat_time: time
    start_time: time | None = None
    session_number: int = 1
    session_label: str | None = None
    timezone: str = "Europe/London"
    evidence: ExtractorEvidence


class ExtractorWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    target_label: str | None = None


class ExtractorResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ExtractorRow] = Field(default_factory=list)
    warnings: list[ExtractorWarning] = Field(default_factory=list)
    no_schedule_reason: str | None = None

    @model_validator(mode="after")
    def _check_empty_rows_have_reason(self) -> ExtractorResult:
        if not self.rows and not self.no_schedule_reason:
            msg = "rows=[] requires no_schedule_reason"
            raise ValueError(msg)
        return self


@dataclass
class ExtractContext:
    source_id: str
    mosque_name: str
    mosque_id: str | None
    source_url: str
    timezone: str
    artifacts: Mapping[str, ExtractorArtifact]
    extra: dict[str, Any] = field(default_factory=dict)

    def artifact(self, label: str) -> ExtractorArtifact:
        if label not in self.artifacts:
            msg = f"target artifact not available: {label}"
            raise KeyError(msg)
        return self.artifacts[label]

    def evidence(
        self,
        *,
        target_label: str,
        extractor_key: str,
        extractor_version: str,
        artifact_id: str | None = None,
        raw_text: str | None = None,
        selector: str | None = None,
        derivation: dict[str, Any] | None = None,
        notes: str | None = None,
    ) -> ExtractorEvidence:
        target_url = self.artifacts[target_label].target_url
        return ExtractorEvidence(
            target_label=target_label,
            target_url=target_url,
            artifact_id=artifact_id,
            extractor_key=extractor_key,
            extractor_version=extractor_version,
            raw_text=raw_text,
            selector=selector,
            derivation=derivation,
            notes=notes,
        )


class BaseMosqueWebsiteExtractor(ABC):
    """Strict base class for repo-owned deterministic website extractors."""

    key: str
    version: str
    source_match: SourceMatch = SourceMatch()
    refresh_policy: RefreshPolicy
    targets: tuple[TargetSpec, ...] = ()

    def __init__(self) -> None:
        if not getattr(self, "key", None):
            msg = "Extractor.key is required"
            raise ValueError(msg)
        if not getattr(self, "version", None):
            msg = "Extractor.version is required"
            raise ValueError(msg)

    @abstractmethod
    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        raise NotImplementedError
