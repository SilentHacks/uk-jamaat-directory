"""Add failure taxonomy + attempt tracking to authoring tasks.

Revision ID: 008_authoring_taxonomy
Revises: 007_authoring_tasks
Create Date: 2026-06-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "008_authoring_taxonomy"
down_revision = "007_authoring_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "extractor_authoring_tasks",
        sa.Column("failure_category", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_extractor_authoring_tasks_failure_category",
        "extractor_authoring_tasks",
        ["failure_category"],
    )
    op.add_column(
        "extractor_authoring_tasks",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "extractor_authoring_tasks",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("extractor_authoring_tasks", "last_attempt_at")
    op.drop_column("extractor_authoring_tasks", "attempts")
    op.drop_index(
        "ix_extractor_authoring_tasks_failure_category",
        table_name="extractor_authoring_tasks",
    )
    op.drop_column("extractor_authoring_tasks", "failure_category")
