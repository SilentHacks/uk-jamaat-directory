from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.schedules.parse import parse_prayer


class StandardFeedTimeRow(BaseModel):
    date: date
    prayer: Prayer
    start_time: str | None = None
    jamaat_time: str
    session_number: int = Field(default=1, ge=1)
    session_label: str | None = None

    @field_validator("prayer", mode="before")
    @classmethod
    def normalize_prayer(cls, value: object) -> Prayer:
        if isinstance(value, Prayer):
            return value
        if not isinstance(value, str):
            msg = "prayer must be a string"
            raise TypeError(msg)
        return parse_prayer(value)


class StandardFeedDocument(BaseModel):
    schema_version: str = Field(min_length=1)
    mosque_name: str | None = None
    timezone: str = "Europe/London"
    updated_at: datetime | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    times: list[StandardFeedTimeRow] = Field(default_factory=list)
