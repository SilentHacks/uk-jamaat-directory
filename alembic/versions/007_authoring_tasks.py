"""Add authoring tasks for the overnight extractor orchestrator.

Revision ID: 007_authoring_tasks
Revises: 006_repo_extractors
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "007_authoring_tasks"
down_revision = "006_repo_extractors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extractor_authoring_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "status",
            sa.String(length=40),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("discovered_url", sa.Text(), nullable=True),
        sa.Column(
            "target_kind",
            sa.String(length=40),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("extractor_key", sa.String(length=180), nullable=True),
        sa.Column("extractor_version", sa.String(length=80), nullable=True),
        sa.Column("script_path", sa.Text(), nullable=True),
        sa.Column("agent_model", sa.String(length=120), nullable=True),
        sa.Column("agent_command", sa.Text(), nullable=True),
        sa.Column("agent_duration_ms", sa.Integer(), nullable=True),
        sa.Column("agent_stdout_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "validation_issues",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_extractor_authoring_tasks_status",
        "extractor_authoring_tasks",
        ["status"],
    )
    op.create_index(
        "ix_extractor_authoring_tasks_target_kind",
        "extractor_authoring_tasks",
        ["target_kind"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extractor_authoring_tasks_target_kind",
        table_name="extractor_authoring_tasks",
    )
    op.drop_index(
        "ix_extractor_authoring_tasks_status",
        table_name="extractor_authoring_tasks",
    )
    op.drop_table("extractor_authoring_tasks")
