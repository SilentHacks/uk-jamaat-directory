from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AdminMosqueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: str = "GB"
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str = "active"
    public_notes: str | None = None


class AdminMosqueUpdate(BaseModel):
    name: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: str | None = None
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    status: str | None = None
    public_notes: str | None = None


class AdminSourceAttach(BaseModel):
    source_type: str
    external_id: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    display_name: str | None = None
    publication_policy: str = "unknown"
    confidence: str = "community"
    attribution: str | None = None


class AdminAliasCreate(BaseModel):
    alias: str = Field(min_length=1, max_length=255)


class AdminMosqueMerge(BaseModel):
    duplicate_mosque_id: uuid.UUID
    reason: str | None = None


class AdminMosqueResponse(BaseModel):
    directory_mosque_id: uuid.UUID
    name: str
    status: str


class AdminDiscoveryLeadCreate(BaseModel):
    query: str = Field(min_length=1)
    notes: str | None = None
    location_hint: str | None = None


class AdminDiscoveryLeadResponse(BaseModel):
    lead_id: uuid.UUID
    status: str
    message: str
