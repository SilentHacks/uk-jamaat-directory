from __future__ import annotations

from pydantic import BaseModel, Field


class CommunityMosqueSubmission(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address_line1: str | None = None
    city: str | None = None
    postcode: str | None = None
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    message: str | None = None
    submitter_name: str | None = None
    submitter_email: str | None = None


class CommunityMosqueSubmissionResponse(BaseModel):
    submission_id: str
    status: str
    message: str
