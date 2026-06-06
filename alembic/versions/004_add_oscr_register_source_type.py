"""Add OSCR register source type.

Revision ID: 004_add_oscr_register_source_type
Revises: 003_muslimsinbritain
Create Date: 2026-06-06
"""
from __future__ import annotations

from alembic import op

revision = "004_oscr_register"
down_revision = "003_muslimsinbritain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE source_type ADD VALUE IF NOT EXISTS 'oscr_register'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without recreating the type.
    pass
