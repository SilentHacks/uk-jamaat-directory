from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class CommunityMosqueSubmission(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address_line1: str | None = None
    city: str | None = None
    postcode: str | None = None
    website_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    message: str | None = Field(default=None, max_length=2000)
    submitter_name: str | None = None
    submitter_email: str | None = None


class CommunityMosqueSubmissionResponse(BaseModel):
    submission_id: str
    status: str
    message: str


class ScheduleSubmissionRow(BaseModel):
    date: date
    prayer: str
    start_time: str | None = None
    jamaat_time: str
    session_number: int = Field(default=1, ge=1)
    session_label: str | None = None


class MosqueScheduleSubmission(BaseModel):
    timezone: str = "Europe/London"
    schedules: list[ScheduleSubmissionRow] = Field(min_length=1)
    message: str | None = Field(default=None, max_length=2000)
    submitter_name: str | None = None
    submitter_email: str | None = None


class MosqueCorrectionSubmission(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    occurrence_id: uuid.UUID | None = None
    suggested: dict[str, object] = Field(default_factory=dict)
    submitter_name: str | None = None
    submitter_email: str | None = None


class MosqueClaimSubmission(BaseModel):
    claimant_name: str = Field(min_length=1, max_length=255)
    claimant_email: str = Field(min_length=3, max_length=255)
    claimant_role: str | None = Field(default=None, max_length=120)
    verification_evidence: dict[str, object] = Field(default_factory=dict)


class ContributionAcceptedResponse(BaseModel):
    submission_id: str
    status: str
    message: str
