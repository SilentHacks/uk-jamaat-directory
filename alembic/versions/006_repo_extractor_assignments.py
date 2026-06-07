"""Add repo extractor assignments.

Revision ID: 006_repo_extractors
Revises: 005_retire_standard_feed
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "006_repo_extractors"
down_revision = "005_retire_standard_feed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_extractor_assignments",
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("extractor_key", sa.String(length=180), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("run_frequency", sa.String(length=40), nullable=False),
        sa.Column("run_timezone", sa.String(length=64), nullable=False, server_default="Europe/London"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_source_extractor_assignments_status_next_run_at",
        "source_extractor_assignments",
        ["status", "next_run_at"],
    )
    op.create_index(
        "ix_source_extractor_assignments_extractor_key",
        "source_extractor_assignments",
        ["extractor_key"],
    )

    op.execute(
        """
        UPDATE mosque_sources
        SET metadata = COALESCE(metadata, '{}'::jsonb)
          - 'extraction_profile'
          - 'profile_status'
          - 'profile_model'
          - 'profiled_at'
          - 'profile_version'
        WHERE source_type = 'mosque_website'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_source_extractor_assignments_extractor_key",
        table_name="source_extractor_assignments",
    )
    op.drop_index(
        "ix_source_extractor_assignments_status_next_run_at",
        table_name="source_extractor_assignments",
    )
    op.drop_table("source_extractor_assignments")
