"""Initial directory schema.

Revision ID: 001_initial_directory_schema
Revises:
Create Date: 2026-06-04
"""

from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001_initial_directory_schema"
down_revision = None
branch_labels = None
depends_on = None


SOURCE_PUBLICATION_POLICY = postgresql.ENUM(
    "public_redistribution_allowed",
    "private_use_only",
    "unknown",
    "blocked",
    name="source_publication_policy",
    create_type=False,
)
SOURCE_TYPE = postgresql.ENUM(
    "mylocalmasjid",
    "standard_feed",
    "mosque_website",
    "openstreetmap",
    "charity_register",
    "community",
    "manual",
    "partner_feed",
    name="source_type",
    create_type=False,
)
CONFIDENCE = postgresql.ENUM(
    "verified",
    "official_import",
    "partner_import",
    "community",
    "calculated",
    name="confidence",
    create_type=False,
)
FRESHNESS_STATUS = postgresql.ENUM(
    "fresh",
    "stale",
    "missing_today",
    "missing_next_7_days",
    "source_failed",
    "needs_review",
    name="freshness_status",
    create_type=False,
)
PRAYER = postgresql.ENUM(
    "fajr",
    "dhuhr",
    "asr",
    "maghrib",
    "isha",
    "jumuah",
    name="prayer",
    create_type=False,
)
MOSQUE_STATUS = postgresql.ENUM(
    "active",
    "inactive",
    "needs_review",
    "duplicate",
    name="mosque_status",
    create_type=False,
)
CANDIDATE_STATUS = postgresql.ENUM(
    "pending",
    "approved",
    "rejected",
    "superseded",
    name="candidate_status",
    create_type=False,
)
ARTIFACT_STATUS = postgresql.ENUM(
    "fetched",
    "unchanged",
    "failed",
    name="artifact_status",
    create_type=False,
)
EXTRACTION_KIND = postgresql.ENUM(
    "deterministic",
    "ocr",
    "ai",
    "manual",
    name="extraction_kind",
    create_type=False,
)
CLAIM_STATUS = postgresql.ENUM(
    "pending",
    "verified",
    "rejected",
    "revoked",
    name="claim_status",
    create_type=False,
)
CORRECTION_STATUS = postgresql.ENUM(
    "pending",
    "accepted",
    "rejected",
    name="correction_status",
    create_type=False,
)
CHANGE_EVENT_TYPE = postgresql.ENUM(
    "mosque_created",
    "mosque_updated",
    "occurrence_published",
    "occurrence_removed",
    "source_updated",
    name="change_event_type",
    create_type=False,
)

ENUM_TYPES = (
    SOURCE_PUBLICATION_POLICY,
    SOURCE_TYPE,
    CONFIDENCE,
    FRESHNESS_STATUS,
    PRAYER,
    MOSQUE_STATUS,
    CANDIDATE_STATUS,
    ARTIFACT_STATUS,
    EXTRACTION_KIND,
    CLAIM_STATUS,
    CORRECTION_STATUS,
    CHANGE_EVENT_TYPE,
)


def uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    bind = op.get_bind()
    for enum in ENUM_TYPES:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "mosques",
        uuid_pk(),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("address_line1", sa.String(length=255)),
        sa.Column("address_line2", sa.String(length=255)),
        sa.Column("city", sa.String(length=120)),
        sa.Column("county", sa.String(length=120)),
        sa.Column("postcode", sa.String(length=16)),
        sa.Column("country", sa.String(length=2), nullable=False, server_default="GB"),
        sa.Column("website_url", sa.Text()),
        sa.Column("location", geoalchemy2.Geography(geometry_type="POINT", srid=4326)),
        sa.Column("status", MOSQUE_STATUS, nullable=False, server_default="needs_review"),
        sa.Column("public_notes", sa.Text()),
        *timestamps(),
    )
    op.create_index("ix_mosques_normalized_name", "mosques", ["normalized_name"])
    op.create_index("ix_mosques_city", "mosques", ["city"])
    op.create_index("ix_mosques_postcode", "mosques", ["postcode"])
    op.create_index("ix_mosques_location", "mosques", ["location"], postgresql_using="gist")

    op.create_table(
        "dataset_versions",
        uuid_pk(),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "manifest", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("checksum", sa.String(length=128)),
        *timestamps(),
        sa.UniqueConstraint("version", name="uq_dataset_versions_version"),
    )

    op.create_table(
        "mosque_sources",
        uuid_pk(),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="SET NULL"),
        ),
        sa.Column("source_type", SOURCE_TYPE, nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("display_name", sa.String(length=255)),
        sa.Column(
            "publication_policy",
            SOURCE_PUBLICATION_POLICY,
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("confidence", CONFIDENCE, nullable=False, server_default="community"),
        sa.Column("license_name", sa.String(length=120)),
        sa.Column("attribution", sa.Text()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
        sa.UniqueConstraint("source_type", "external_id", name="uq_mosque_source_identity"),
    )
    op.create_index("ix_mosque_sources_mosque_id", "mosque_sources", ["mosque_id"])

    op.create_table(
        "mosque_aliases",
        uuid_pk(),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("source_type", SOURCE_TYPE),
        *timestamps(),
        sa.UniqueConstraint("mosque_id", "alias", name="uq_mosque_alias"),
    )
    op.create_index("ix_mosque_aliases_mosque_id", "mosque_aliases", ["mosque_id"])
    op.create_index("ix_mosque_aliases_normalized_alias", "mosque_aliases", ["normalized_alias"])

    op.create_table(
        "mosque_attributes",
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "facilities", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("madhab", sa.String(length=120)),
        sa.Column("affiliation", sa.String(length=120)),
        sa.Column("women_space", sa.Boolean()),
        sa.Column("parking", sa.Boolean()),
        sa.Column(
            "accessibility",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        *timestamps(),
    )

    op.create_table(
        "source_artifacts",
        uuid_pk(),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fetched_url", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text()),
        sa.Column("content_type", sa.String(length=120)),
        sa.Column("content_hash", sa.String(length=128)),
        sa.Column("etag", sa.String(length=255)),
        sa.Column("last_modified", sa.String(length=255)),
        sa.Column("status", ARTIFACT_STATUS, nullable=False, server_default="fetched"),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("error_message", sa.Text()),
        *timestamps(),
        sa.UniqueConstraint("source_id", "content_hash", name="uq_source_artifact_hash"),
    )
    op.create_index("ix_source_artifacts_source_id", "source_artifacts", ["source_id"])

    op.create_table(
        "extraction_runs",
        uuid_pk(),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_artifacts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", EXTRACTION_KIND, nullable=False),
        sa.Column("extractor_version", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Numeric(5, 4)),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
    )
    op.create_index("ix_extraction_runs_artifact_id", "extraction_runs", ["artifact_id"])
    op.create_index("ix_extraction_runs_source_id", "extraction_runs", ["source_id"])

    op.create_table(
        "schedule_candidates",
        uuid_pk(),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "extraction_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("extraction_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("prayer", PRAYER, nullable=False),
        sa.Column("start_time", sa.Time(timezone=False)),
        sa.Column("jamaat_time", sa.Time(timezone=False)),
        sa.Column("session_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("session_label", sa.String(length=120)),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/London"),
        sa.Column("confidence", CONFIDENCE, nullable=False, server_default="community"),
        sa.Column("status", CANDIDATE_STATUS, nullable=False, server_default="pending"),
        sa.Column(
            "validation_errors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
    )
    op.create_index("ix_schedule_candidates_mosque_id", "schedule_candidates", ["mosque_id"])
    op.create_index("ix_schedule_candidates_source_id", "schedule_candidates", ["source_id"])
    op.create_index(
        "ix_schedule_candidates_extraction_run_id", "schedule_candidates", ["extraction_run_id"]
    )
    op.create_index("ix_schedule_candidates_date", "schedule_candidates", ["date"])

    op.create_table(
        "schedule_occurrences",
        uuid_pk(),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_candidates.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "dataset_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("prayer", PRAYER, nullable=False),
        sa.Column("start_time", sa.Time(timezone=False)),
        sa.Column("jamaat_time", sa.Time(timezone=False), nullable=False),
        sa.Column("session_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("session_label", sa.String(length=120)),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="Europe/London"),
        sa.Column("confidence", CONFIDENCE, nullable=False),
        sa.Column(
            "freshness_status", FRESHNESS_STATUS, nullable=False, server_default="needs_review"
        ),
        sa.Column("source_url", sa.Text()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint(
            "mosque_id",
            "date",
            "prayer",
            "session_number",
            "dataset_version_id",
            name="uq_schedule_occurrence_versioned_session",
        ),
    )
    op.create_index("ix_schedule_occurrences_mosque_id", "schedule_occurrences", ["mosque_id"])
    op.create_index("ix_schedule_occurrences_source_id", "schedule_occurrences", ["source_id"])
    op.create_index(
        "ix_schedule_occurrences_candidate_id", "schedule_occurrences", ["candidate_id"]
    )
    op.create_index(
        "ix_schedule_occurrences_dataset_version_id", "schedule_occurrences", ["dataset_version_id"]
    )
    op.create_index("ix_schedule_occurrences_date", "schedule_occurrences", ["date"])

    op.create_table(
        "source_health",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "freshness_status", FRESHNESS_STATUS, nullable=False, server_default="needs_review"
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_7_days_coverage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text()),
        *timestamps(),
    )

    op.create_table(
        "change_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", CHANGE_EVENT_TYPE, nullable=False),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_occurrences.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "dataset_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dataset_versions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
    )
    op.create_index("ix_change_events_mosque_id", "change_events", ["mosque_id"])
    op.create_index("ix_change_events_occurrence_id", "change_events", ["occurrence_id"])
    op.create_index("ix_change_events_dataset_version_id", "change_events", ["dataset_version_id"])

    op.create_table(
        "moderation_actions",
        uuid_pk(),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
    )

    op.create_table(
        "mosque_claims",
        uuid_pk(),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claimant_name", sa.String(length=255), nullable=False),
        sa.Column("claimant_email", sa.String(length=255), nullable=False),
        sa.Column("claimant_role", sa.String(length=120)),
        sa.Column("status", CLAIM_STATUS, nullable=False, server_default="pending"),
        sa.Column(
            "verification_evidence",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        *timestamps(),
    )
    op.create_index("ix_mosque_claims_mosque_id", "mosque_claims", ["mosque_id"])

    op.create_table(
        "corrections",
        uuid_pk(),
        sa.Column(
            "mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedule_occurrences.id", ondelete="SET NULL"),
        ),
        sa.Column("submitter_name", sa.String(length=255)),
        sa.Column("submitter_email", sa.String(length=255)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", CORRECTION_STATUS, nullable=False, server_default="pending"),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        *timestamps(),
    )
    op.create_index("ix_corrections_mosque_id", "corrections", ["mosque_id"])
    op.create_index("ix_corrections_occurrence_id", "corrections", ["occurrence_id"])


def downgrade() -> None:
    op.drop_index("ix_corrections_occurrence_id", table_name="corrections")
    op.drop_index("ix_corrections_mosque_id", table_name="corrections")
    op.drop_table("corrections")
    op.drop_index("ix_mosque_claims_mosque_id", table_name="mosque_claims")
    op.drop_table("mosque_claims")
    op.drop_table("moderation_actions")
    op.drop_index("ix_change_events_dataset_version_id", table_name="change_events")
    op.drop_index("ix_change_events_occurrence_id", table_name="change_events")
    op.drop_index("ix_change_events_mosque_id", table_name="change_events")
    op.drop_table("change_events")
    op.drop_table("source_health")
    op.drop_index("ix_schedule_occurrences_date", table_name="schedule_occurrences")
    op.drop_index("ix_schedule_occurrences_dataset_version_id", table_name="schedule_occurrences")
    op.drop_index("ix_schedule_occurrences_candidate_id", table_name="schedule_occurrences")
    op.drop_index("ix_schedule_occurrences_source_id", table_name="schedule_occurrences")
    op.drop_index("ix_schedule_occurrences_mosque_id", table_name="schedule_occurrences")
    op.drop_table("schedule_occurrences")
    op.drop_index("ix_schedule_candidates_date", table_name="schedule_candidates")
    op.drop_index("ix_schedule_candidates_extraction_run_id", table_name="schedule_candidates")
    op.drop_index("ix_schedule_candidates_source_id", table_name="schedule_candidates")
    op.drop_index("ix_schedule_candidates_mosque_id", table_name="schedule_candidates")
    op.drop_table("schedule_candidates")
    op.drop_index("ix_extraction_runs_source_id", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_artifact_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    op.drop_index("ix_source_artifacts_source_id", table_name="source_artifacts")
    op.drop_table("source_artifacts")
    op.drop_table("mosque_attributes")
    op.drop_index("ix_mosque_aliases_normalized_alias", table_name="mosque_aliases")
    op.drop_index("ix_mosque_aliases_mosque_id", table_name="mosque_aliases")
    op.drop_table("mosque_aliases")
    op.drop_index("ix_mosque_sources_mosque_id", table_name="mosque_sources")
    op.drop_table("mosque_sources")
    op.drop_table("dataset_versions")
    op.drop_index("ix_mosques_location", table_name="mosques")
    op.drop_index("ix_mosques_postcode", table_name="mosques")
    op.drop_index("ix_mosques_city", table_name="mosques")
    op.drop_index("ix_mosques_normalized_name", table_name="mosques")
    op.drop_table("mosques")

    bind = op.get_bind()
    for enum in reversed(ENUM_TYPES):
        enum.drop(bind, checkfirst=True)
