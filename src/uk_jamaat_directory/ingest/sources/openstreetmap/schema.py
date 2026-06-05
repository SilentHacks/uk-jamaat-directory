from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OsmPlaceRecord(BaseModel):
    osm_type: Literal["node", "way", "relation"]
    osm_id: int
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    address_line1: str | None = None
    city: str | None = None
    postcode: str | None = None
    country: str = "GB"
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    religion: str | None = None
    denomination: str | None = None
    source_url: str | None = None
    source_record_updated_at: datetime | None = None
    osm_version: int | None = None
    osm_changeset: int | None = None
    osm_user: str | None = None

    @property
    def external_id(self) -> str:
        return f"{self.osm_type}/{self.osm_id}"


class OsmImportBundle(BaseModel):
    format_version: Literal["1"] = "1"
    exported_at: datetime | None = None
    attribution: str = "© OpenStreetMap contributors (ODbL 1.0)"
    places: list[OsmPlaceRecord] = Field(default_factory=list)
