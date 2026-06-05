"""Add MuslimsInBritain source type.

Revision ID: 003_add_muslimsinbritain_source_type
Revises: 002_identity_match_reviews
Create Date: 2026-06-05
"""

from __future__ import annotations

from alembic import op

revision = "003_muslimsinbritain"
down_revision = "002_identity_match_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'muslimsinbritain'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without recreating the type.
    pass
