from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field


class PublicSourceProvenance(BaseModel):
    source_type: str
    source_url: str | None = None
    confidence: str
    attribution: str | None = None
    last_seen_at: datetime | None = None


class PublicScheduleOccurrence(BaseModel):
    directory_mosque_id: UUID
    date: date
    prayer: str
    start_time: time | None = None
    jamaat_time: time
    session_number: int = 1
    session_label: str | None = None
    timezone: str
    confidence: str
    source_type: str
    source_url: str | None = None
    last_verified_at: datetime | None = None
    freshness_status: str
    dataset_version: str | None = None


class MosqueSummaryPublic(BaseModel):
    directory_mosque_id: UUID
    name: str
    city: str | None = None
    postcode: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str
    distance_metres: float | None = None


class MosqueDetailPublic(BaseModel):
    directory_mosque_id: UUID
    name: str
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: str
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str
    aliases: list[str] = Field(default_factory=list)
    sources: list[PublicSourceProvenance] = Field(default_factory=list)
    facilities: dict[str, bool] = Field(default_factory=dict)


class MosqueListResponse(BaseModel):
    items: list[MosqueSummaryPublic]
    count: int
    limit: int
    offset: int


class TimesResponse(BaseModel):
    directory_mosque_id: UUID
    from_date: date
    to_date: date
    items: list[PublicScheduleOccurrence]


class NearbyTimeItem(BaseModel):
    directory_mosque_id: UUID
    mosque_name: str
    distance_metres: float
    occurrence: PublicScheduleOccurrence


class NearbyTimesResponse(BaseModel):
    date: date
    latitude: float
    longitude: float
    radius_m: float
    items: list[NearbyTimeItem]


class ChangeEventPublic(BaseModel):
    id: int
    event_type: str
    occurred_at: datetime
    directory_mosque_id: UUID | None = None
    occurrence_id: UUID | None = None
    dataset_version: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class ChangeFeedResponse(BaseModel):
    items: list[ChangeEventPublic]
    count: int
    limit: int
    since: int | None = None


class SnapshotFormatInfo(BaseModel):
    format: str
    url: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None


class SnapshotResponse(BaseModel):
    version: str
    schema_version: str
    published_at: datetime | None = None
    checksum: str | None = None
    attribution: list[str] = Field(default_factory=list)
    formats: list[SnapshotFormatInfo] = Field(default_factory=list)
