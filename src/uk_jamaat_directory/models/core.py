from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from uk_jamaat_directory.db.base import Base
from uk_jamaat_directory.domain import (
    ArtifactStatus,
    CandidateStatus,
    ChangeEventType,
    ClaimStatus,
    Confidence,
    CorrectionStatus,
    ExtractionKind,
    FreshnessStatus,
    MosqueStatus,
    Prayer,
    SourcePublicationPolicy,
    SourceType,
)


def enum_type(enum_class: type, name: str) -> Enum:
    return Enum(enum_class, name=name, values_callable=lambda item: [value.value for value in item])


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Mosque(TimestampMixin, Base):
    __tablename__ = "mosques"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    county: Mapped[str | None] = mapped_column(String(120))
    postcode: Mapped[str | None] = mapped_column(String(16), index=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, server_default="GB")
    website_url: Mapped[str | None] = mapped_column(Text)
    location: Mapped[Any | None] = mapped_column(Geography(geometry_type="POINT", srid=4326))
    status: Mapped[MosqueStatus] = mapped_column(
        enum_type(MosqueStatus, "mosque_status"),
        nullable=False,
        server_default=MosqueStatus.NEEDS_REVIEW.value,
    )
    public_notes: Mapped[str | None] = mapped_column(Text)

    aliases: Mapped[list[MosqueAlias]] = relationship(back_populates="mosque")
    sources: Mapped[list[MosqueSource]] = relationship(back_populates="mosque")
    attributes: Mapped[MosqueAttribute | None] = relationship(back_populates="mosque")


class MosqueAlias(TimestampMixin, Base):
    __tablename__ = "mosque_aliases"
    __table_args__ = (UniqueConstraint("mosque_id", "alias", name="uq_mosque_alias"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mosque_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosques.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[SourceType | None] = mapped_column(enum_type(SourceType, "source_type"))

    mosque: Mapped[Mosque] = relationship(back_populates="aliases")


class MosqueSource(TimestampMixin, Base):
    __tablename__ = "mosque_sources"
    __table_args__ = (
        UniqueConstraint("source_type", "external_id", name="uq_mosque_source_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mosque_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mosques.id", ondelete="SET NULL"),
        index=True,
    )
    source_type: Mapped[SourceType] = mapped_column(
        enum_type(SourceType, "source_type"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(String(255))
    publication_policy: Mapped[SourcePublicationPolicy] = mapped_column(
        enum_type(SourcePublicationPolicy, "source_publication_policy"),
        nullable=False,
        server_default=SourcePublicationPolicy.UNKNOWN.value,
    )
    confidence: Mapped[Confidence] = mapped_column(
        enum_type(Confidence, "confidence"),
        nullable=False,
        server_default=Confidence.COMMUNITY.value,
    )
    license_name: Mapped[str | None] = mapped_column(String(120))
    attribution: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    mosque: Mapped[Mosque | None] = relationship(back_populates="sources")


class MosqueAttribute(TimestampMixin, Base):
    __tablename__ = "mosque_attributes"

    mosque_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosques.id", ondelete="CASCADE"),
        primary_key=True,
    )
    facilities: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    madhab: Mapped[str | None] = mapped_column(String(120))
    affiliation: Mapped[str | None] = mapped_column(String(120))
    women_space: Mapped[bool | None] = mapped_column(Boolean)
    parking: Mapped[bool | None] = mapped_column(Boolean)
    accessibility: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    mosque: Mapped[Mosque] = relationship(back_populates="attributes")


class SourceArtifact(TimestampMixin, Base):
    __tablename__ = "source_artifacts"
    __table_args__ = (
        UniqueConstraint("source_id", "content_hash", name="uq_source_artifact_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fetched_url: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str | None] = mapped_column(String(128))
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ArtifactStatus] = mapped_column(
        enum_type(ArtifactStatus, "artifact_status"),
        nullable=False,
        server_default=ArtifactStatus.FETCHED.value,
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class ExtractionRun(TimestampMixin, Base):
    __tablename__ = "extraction_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_artifacts.id", ondelete="SET NULL"),
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[ExtractionKind] = mapped_column(
        enum_type(ExtractionKind, "extraction_kind"),
        nullable=False,
    )
    extractor_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class ScheduleCandidate(TimestampMixin, Base):
    __tablename__ = "schedule_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mosque_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mosques.id", ondelete="SET NULL"),
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="SET NULL"),
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    prayer: Mapped[Prayer] = mapped_column(enum_type(Prayer, "prayer"), nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time(timezone=False))
    jamaat_time: Mapped[time | None] = mapped_column(Time(timezone=False))
    session_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    session_label: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/London"
    )
    confidence: Mapped[Confidence] = mapped_column(
        enum_type(Confidence, "confidence"),
        nullable=False,
        server_default=Confidence.COMMUNITY.value,
    )
    status: Mapped[CandidateStatus] = mapped_column(
        enum_type(CandidateStatus, "candidate_status"),
        nullable=False,
        server_default=CandidateStatus.PENDING.value,
    )
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class DatasetVersion(TimestampMixin, Base):
    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    version: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    checksum: Mapped[str | None] = mapped_column(String(128))


class ScheduleOccurrence(TimestampMixin, Base):
    __tablename__ = "schedule_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "mosque_id",
            "date",
            "prayer",
            "session_number",
            "dataset_version_id",
            name="uq_schedule_occurrence_versioned_session",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mosque_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosques.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_candidates.id", ondelete="SET NULL"),
        index=True,
    )
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    prayer: Mapped[Prayer] = mapped_column(enum_type(Prayer, "prayer"), nullable=False)
    start_time: Mapped[time | None] = mapped_column(Time(timezone=False))
    jamaat_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    session_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    session_label: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/London"
    )
    confidence: Mapped[Confidence] = mapped_column(
        enum_type(Confidence, "confidence"),
        nullable=False,
    )
    freshness_status: Mapped[FreshnessStatus] = mapped_column(
        enum_type(FreshnessStatus, "freshness_status"),
        nullable=False,
        server_default=FreshnessStatus.NEEDS_REVIEW.value,
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceHealth(TimestampMixin, Base):
    __tablename__ = "source_health"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    freshness_status: Mapped[FreshnessStatus] = mapped_column(
        enum_type(FreshnessStatus, "freshness_status"),
        nullable=False,
        server_default=FreshnessStatus.NEEDS_REVIEW.value,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_7_days_coverage: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    message: Mapped[str | None] = mapped_column(Text)


class ExtractorAuthoringTask(TimestampMixin, Base):
    __tablename__ = "extractor_authoring_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    source: Mapped[MosqueSource] = relationship("MosqueSource")
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="queued", index=True
    )
    discovered_url: Mapped[str | None] = mapped_column(Text)
    target_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unknown", index=True
    )
    extractor_key: Mapped[str | None] = mapped_column(String(180))
    extractor_version: Mapped[str | None] = mapped_column(String(80))
    script_path: Mapped[str | None] = mapped_column(Text)
    agent_model: Mapped[str | None] = mapped_column(String(120))
    agent_command: Mapped[str | None] = mapped_column(Text)
    agent_duration_ms: Mapped[int | None] = mapped_column(Integer)
    agent_stdout_excerpt: Mapped[str | None] = mapped_column(Text)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    error: Mapped[str | None] = mapped_column(Text)
    failure_category: Mapped[str | None] = mapped_column(String(40), index=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class SourceExtractorAssignment(TimestampMixin, Base):
    __tablename__ = "source_extractor_assignments"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        primary_key=True,
    )
    extractor_key: Mapped[str] = mapped_column(String(180), nullable=False, index=True)
    extractor_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="active")
    run_frequency: Mapped[str] = mapped_column(String(40), nullable=False)
    run_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="Europe/London"
    )
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class ChangeEvent(TimestampMixin, Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[ChangeEventType] = mapped_column(
        enum_type(ChangeEventType, "change_event_type"),
        nullable=False,
    )
    mosque_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mosques.id", ondelete="SET NULL"),
        index=True,
    )
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_occurrences.id", ondelete="SET NULL"),
        index=True,
    )
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class IdentityMatchReview(TimestampMixin, Base):
    __tablename__ = "identity_match_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        index=True,
    )
    proposed_mosque_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mosques.id", ondelete="SET NULL"),
        index=True,
    )
    score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reasons: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    alternatives: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    reviewer: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModerationAction(TimestampMixin, Base):
    __tablename__ = "moderation_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class MosqueClaim(TimestampMixin, Base):
    __tablename__ = "mosque_claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mosque_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mosques.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claimant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    claimant_email: Mapped[str] = mapped_column(String(255), nullable=False)
    claimant_role: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[ClaimStatus] = mapped_column(
        enum_type(ClaimStatus, "claim_status"),
        nullable=False,
        server_default=ClaimStatus.PENDING.value,
    )
    verification_evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Correction(TimestampMixin, Base):
    __tablename__ = "corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    mosque_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mosques.id", ondelete="SET NULL"),
        index=True,
    )
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedule_occurrences.id", ondelete="SET NULL"),
        index=True,
    )
    submitter_name: Mapped[str | None] = mapped_column(String(255))
    submitter_email: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CorrectionStatus] = mapped_column(
        enum_type(CorrectionStatus, "correction_status"),
        nullable=False,
        server_default=CorrectionStatus.PENDING.value,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
