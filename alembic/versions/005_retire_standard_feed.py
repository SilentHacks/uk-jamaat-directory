"""Migrate standard_feed rows to mosque_website; retire standard_feed.

- Existing standard_feed rows are upgraded to mosque_website when no
  mosque_website source already exists for that mosque.
- Rows whose mosques already have a mosque_website are deleted.
- The standard_feed enum value is left as a documented dead value to
  avoid the risk of recreating the source_type enum type.

Revision ID: 005_retire_standard_feed
Revises: 004_oscr_register
Create Date: 2026-06-06
"""

from __future__ import annotations

from alembic import op

revision = "005_retire_standard_feed"
down_revision = "004_oscr_register"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert standard_feed rows to mosque_website where no
    # mosque_website already exists for the same mosque.
    op.execute(
        """
        UPDATE mosque_sources ms
        SET
          source_type = 'mosque_website',
          external_id = 'web-' || ms.mosque_id::text,
          source_url = COALESCE(m.website_url, 'https://' || ms.external_id),
          metadata = COALESCE(ms.metadata, '{}'::jsonb) || jsonb_build_object(
            'migrated_from', 'standard_feed',
            'homepage_url', COALESCE(m.website_url, 'https://' || ms.external_id),
            'profile_status', 'pending'
          )
        FROM mosques m
        WHERE ms.mosque_id = m.id
          AND ms.source_type = 'standard_feed'
          AND NOT EXISTS (
            SELECT 1 FROM mosque_sources existing
            WHERE existing.mosque_id = ms.mosque_id
              AND existing.source_type = 'mosque_website'
          )
        """
    )

    # Delete remaining standard_feed rows (duplicates where a
    # mosque_website already existed for that mosque).
    op.execute("DELETE FROM mosque_sources WHERE source_type = 'standard_feed'")


def downgrade() -> None:
    # This migration is one-way. Reversing would require re-creating
    # standard_feed rows without knowledge of original external_ids,
    # source_urls, or metadata. The dead enum value remains in Postgres.
    pass
