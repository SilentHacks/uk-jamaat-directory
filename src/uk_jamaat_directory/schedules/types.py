from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from enum import StrEnum

from uk_jamaat_directory.domain import Prayer


@dataclass(frozen=True)
class ScheduleCandidateInput:
    date: date
    prayer: Prayer
    session_number: int
    session_label: str | None
    timezone: str
    start_time: time | None = None
    jamaat_time: time | None = None


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass
class ValidationIssue:
    code: str
    severity: IssueSeverity
    message: str
    field: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.field is not None:
            payload["field"] = self.field
        return payload


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == IssueSeverity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == IssueSeverity.WARNING]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_error_list(self) -> list[dict[str, str]]:
        return [issue.to_dict() for issue in self.issues]


@dataclass
class ValidateBatchResult:
    examined: int = 0
    approved: int = 0
    rejected: int = 0
    pending: int = 0
    skipped: int = 0


@dataclass
class PublishResult:
    dataset_version: str | None = None
    published: int = 0
    skipped_policy: int = 0
    skipped_validation: int = 0
    carried_forward: int = 0
    removed_occurrences: int = 0
    change_events: int = 0
    errors: list[str] = field(default_factory=list)
