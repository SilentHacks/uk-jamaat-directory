from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from uk_jamaat_directory.ingest.normalize import normalize_postcode

MibCountry = Literal["GB", "IE"]
MibRecordClass = Literal[
    "mosque",
    "prayer_room",
    "hired_hall",
    "multi_faith",
    "defunct",
    "uncertain",
    "other",
]
MibUsage = Literal["full_time", "jumuah_only", "no_jumuah", "irregular", "unknown"]
MibTriState = Literal["yes", "no", "unknown"]
MibPrecision = Literal["precise", "approximate", "unknown"]
MibConfidence = Literal["high", "low", "unknown"]


class MibMosqueRecord(BaseModel):
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: MibCountry
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    website_url: str | None = None
    source_url: str | None = None
    detail_page_url: str | None = None
    record_class: MibRecordClass = "mosque"
    usage: MibUsage = "unknown"
    capacity: int | None = None
    women_facilities: MibTriState = "unknown"
    location_precision: MibPrecision = "unknown"
    metadata_confidence: MibConfidence = "unknown"
    theme: str | None = None
    management: str | None = None
    data_accuracy: str | None = None
    data_accuracy_code: str | None = None
    data_sources: list[str] = Field(default_factory=list)
    attribution: str = "MuslimsInBritain.org"
    source_record_created_at: datetime | None = None
    source_record_updated_at: datetime | None = None

    @field_validator("postcode", mode="before")
    @classmethod
    def normalize_postcode_value(cls, value: object) -> object:
        if value is None:
            return None
        return normalize_postcode(str(value))


class MibImportBundle(BaseModel):
    format_version: Literal["1"] = "1"
    exported_at: datetime | None = None
    attribution: str = "MuslimsInBritain.org"
    mosques: list[MibMosqueRecord] = Field(default_factory=list)
