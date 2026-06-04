"""Add identity match review queue.

Revision ID: 002_identity_match_reviews
Revises: 001_initial_directory_schema
Create Date: 2026-06-04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "002_identity_match_reviews"
down_revision = "001_initial_directory_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "identity_match_reviews",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosque_sources.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "proposed_mosque_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mosques.id", ondelete="SET NULL"),
        ),
        sa.Column("score", sa.Numeric(5, 4)),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column(
            "reasons",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "alternatives",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("reviewer", sa.String(length=255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_identity_match_reviews_source_id",
        "identity_match_reviews",
        ["source_id"],
    )
    op.create_index(
        "ix_identity_match_reviews_proposed_mosque_id",
        "identity_match_reviews",
        ["proposed_mosque_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_identity_match_reviews_proposed_mosque_id", table_name="identity_match_reviews"
    )
    op.drop_index("ix_identity_match_reviews_source_id", table_name="identity_match_reviews")
    op.drop_table("identity_match_reviews")
