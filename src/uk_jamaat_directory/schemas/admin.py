from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

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


class AdminIdentityReviewAction(BaseModel):
    mosque_id: uuid.UUID | None = None
    reason: str | None = None


class AdminBulkIdentityReviewAccept(BaseModel):
    min_score: float = Field(default=0.8, ge=0, le=1)
    limit: int = Field(default=100, ge=1, le=1000)
    dry_run: bool = False


class AdminBulkMosqueActivate(BaseModel):
    source_type: str | None = None
    require_public_source: bool = True
    limit: int = Field(default=1000, ge=1, le=5000)
    dry_run: bool = False


class AdminMosqueResponse(BaseModel):
    directory_mosque_id: uuid.UUID
    name: str
    status: str


class AdminDiscoveryLeadCreate(BaseModel):
    query: str = Field(min_length=1)
    notes: str | None = None
    location_hint: str | None = None
    provider: str = Field(
        default="google",
        description=(
            "Signal source of the lead (e.g. 'google', 'mib_metadata', "
            "'osm_tag_recheck', 'charity_commission', 'wikidata', 'duckduckgo')."
        ),
    )


class AdminDiscoveryLeadResponse(BaseModel):
    lead_id: uuid.UUID
    status: str
    message: str


class AdminCandidateSummary(BaseModel):
    candidate_id: uuid.UUID
    directory_mosque_id: uuid.UUID | None
    source_id: uuid.UUID
    date: date
    prayer: str
    start_time: time | None
    jamaat_time: time | None
    session_number: int
    session_label: str | None
    timezone: str
    confidence: str
    status: str
    validation_errors: list[dict[str, Any]]


class AdminCandidateListResponse(BaseModel):
    items: list[AdminCandidateSummary]
    count: int
    limit: int
    offset: int


class AdminCandidateActionResponse(BaseModel):
    candidate_id: uuid.UUID
    status: str


class AdminCandidateReject(BaseModel):
    reason: str | None = None


class AdminSourceSummary(BaseModel):
    source_id: uuid.UUID
    directory_mosque_id: uuid.UUID | None
    source_type: str
    external_id: str
    source_url: str | None
    display_name: str | None
    publication_policy: str
    confidence: str
    attribution: str | None
    last_seen_at: datetime | None


class AdminSourceListResponse(BaseModel):
    items: list[AdminSourceSummary]
    count: int
    limit: int
    offset: int


class AdminSourceUpdate(BaseModel):
    publication_policy: str | None = None
    confidence: str | None = None
    source_url: str | None = None
    display_name: str | None = None
    attribution: str | None = None


class AdminSourceResponse(BaseModel):
    source_id: uuid.UUID
    directory_mosque_id: uuid.UUID | None
    source_type: str
    external_id: str
    publication_policy: str
    confidence: str


class AdminIdentityOverlapItem(BaseModel):
    source_set: str
    mosque_count: int


class AdminIdentityReviewCandidate(BaseModel):
    mosque_id: uuid.UUID
    name: str
    status: str
    postcode: str | None
    city: str | None
    score: float
    reasons: list[str]


class AdminIdentityReviewSummary(BaseModel):
    review_id: uuid.UUID
    source_id: uuid.UUID | None
    source_type: str | None
    external_id: str | None
    display_name: str | None
    source_url: str | None
    decision: str
    score: float | None
    reasons: list[str]
    status: str
    candidates: list[AdminIdentityReviewCandidate]


class AdminIdentityReviewListResponse(BaseModel):
    items: list[AdminIdentityReviewSummary]
    count: int
    limit: int
    offset: int


class AdminIdentityActionResponse(BaseModel):
    changed: int
    dry_run: bool = False
    review_ids: list[uuid.UUID] = []
    mosque_ids: list[uuid.UUID] = []


class AdminDuplicateBucket(BaseModel):
    normalized_name: str
    postcode: str | None
    mosque_count: int
    mosque_ids: list[uuid.UUID]


class AdminIdentityQualityResponse(BaseModel):
    generated_at: datetime
    mosque_count: int
    active_mosque_count: int
    status_counts: dict[str, int]
    source_count: int
    source_type_counts: dict[str, int]
    policy_counts: dict[str, int]
    source_overlaps: list[AdminIdentityOverlapItem]
    linked_source_count: int
    unlinked_source_count: int
    pending_identity_reviews: int
    missing_postcode_count: int
    missing_coordinates_count: int
    missing_website_count: int
    active_missing_website_count: int
    duplicate_candidate_count: int
    duplicate_buckets: list[AdminDuplicateBucket]


class AdminCoverageResponse(BaseModel):
    generated_at: datetime
    mosque_count: int
    active_mosque_count: int
    source_count: int
    pending_candidates: int
    approved_candidates: int
    rejected_candidates: int
    open_corrections: int
    open_claims: int
    policy_counts: dict[str, int]
    source_type_counts: dict[str, int]
    stale_source_count: int
    pending_identity_reviews: int = 0
    missing_postcode_count: int = 0
    missing_coordinates_count: int = 0
    missing_website_count: int = 0
    duplicate_candidate_count: int = 0


class AdminSourceHealthItem(BaseModel):
    source_id: uuid.UUID
    directory_mosque_id: uuid.UUID | None
    source_type: str
    external_id: str
    freshness_status: str
    next_7_days_coverage: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    consecutive_failures: int
    message: str | None


class AdminSourceHealthResponse(BaseModel):
    items: list[AdminSourceHealthItem]
    count: int
