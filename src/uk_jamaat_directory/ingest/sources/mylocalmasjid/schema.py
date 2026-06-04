from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from uk_jamaat_directory.domain import Prayer

PRAYER_ALIASES: dict[str, Prayer] = {
    "fajr": Prayer.FAJR,
    "dhuhr": Prayer.DHUHR,
    "zuhr": Prayer.DHUHR,
    "asr": Prayer.ASR,
    "maghrib": Prayer.MAGHRIB,
    "isha": Prayer.ISHA,
    "jumuah": Prayer.JUMUAH,
    "jumah": Prayer.JUMUAH,
    "jummah": Prayer.JUMUAH,
}

JAMAAT_TIME_ALIASES = frozenset({"jamaat_time", "jamaat", "jamat", "iqamah", "iqama"})


class MyLocalMasjidScheduleRow(BaseModel):
    date: date
    prayer: Prayer
    start_time: str | None = None
    jamaat_time: str | None = None
    session_number: int = Field(default=1, ge=1)
    session_label: str | None = None
    timezone: str = "Europe/London"

    @field_validator("prayer", mode="before")
    @classmethod
    def normalize_prayer(cls, value: object) -> Prayer:
        if isinstance(value, Prayer):
            return value
        if not isinstance(value, str):
            msg = "prayer must be a string"
            raise TypeError(msg)
        key = value.strip().lower()
        if key not in PRAYER_ALIASES:
            msg = f"unsupported prayer: {value}"
            raise ValueError(msg)
        return PRAYER_ALIASES[key]


class MyLocalMasjidMosqueRecord(BaseModel):
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: str = "GB"
    website_url: str | None = None
    profile_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    attribution: str | None = "MyLocalMasjid"
    linkback_url: str | None = None
    schedules: list[MyLocalMasjidScheduleRow] = Field(default_factory=list)

    @property
    def source_url(self) -> str | None:
        return self.linkback_url or self.profile_url


class MyLocalMasjidImportBundle(BaseModel):
    """Normalized in-memory representation of a MyLocalMasjid import payload."""

    format_version: Literal["1"] = "1"
    exported_at: datetime | None = None
    source_label: str = "mylocalmasjid"
    mosques: list[MyLocalMasjidMosqueRecord] = Field(default_factory=list)
