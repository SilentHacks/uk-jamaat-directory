from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import (
    Confidence,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.normalize import canonical_homepage, normalize_domain
from uk_jamaat_directory.models.core import Mosque, MosqueSource, SourceHealth

_CRAWL_SOURCE_TYPES = (SourceType.STANDARD_FEED, SourceType.MOSQUE_WEBSITE)


@dataclass
class RegisterResult:
    created_mosque_website: int = 0
    skipped_existing: int = 0
    skipped_mlm: int = 0
    skipped_no_domain: int = 0
    synced: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def created(self) -> int:
        return self.created_mosque_website


async def _has_recent_mlm_source(
    session: AsyncSession,
    mosque_id: uuid.UUID,
    *,
    settings: Settings,
) -> bool:
    stmt = (
        select(MosqueSource, SourceHealth)
        .outerjoin(SourceHealth, SourceHealth.source_id == MosqueSource.id)
        .where(MosqueSource.mosque_id == mosque_id)
        .where(MosqueSource.source_type == SourceType.MYLOCALMASJID)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return False

    cutoff = datetime.now(UTC) - timedelta(days=settings.freshness_stale_days)
    for source, health in rows:
        last_seen = source.last_seen_at
        if health is not None and health.last_success_at is not None:
            last_seen = max(filter(None, [last_seen, health.last_success_at]))
        if last_seen is not None and last_seen >= cutoff:
            return True
    return False


async def _existing_crawl_source_for_mosque(
    session: AsyncSession,
    mosque_id: uuid.UUID,
) -> MosqueSource | None:
    return await session.scalar(
        select(MosqueSource).where(
            MosqueSource.mosque_id == mosque_id,
            MosqueSource.source_type.in_(_CRAWL_SOURCE_TYPES),
        )
    )


async def ensure_crawl_sources(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> RegisterResult:
    cfg = settings or get_settings()
    result = RegisterResult()

    stmt = (
        select(Mosque)
        .where(Mosque.status == MosqueStatus.ACTIVE)
        .where(Mosque.website_url.is_not(None))
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    mosques = (await session.execute(stmt)).scalars().all()

    for mosque in mosques:
        domain = normalize_domain(mosque.website_url)
        if domain is None:
            result.skipped_no_domain += 1
            continue

        existing = await _existing_crawl_source_for_mosque(session, mosque.id)
        if existing is not None:
            result.skipped_existing += 1
            continue

        if await _has_recent_mlm_source(session, mosque.id, settings=cfg):
            result.skipped_mlm += 1
            continue

        homepage = canonical_homepage(mosque.website_url)
        if homepage is None:
            result.skipped_no_domain += 1
            continue

        if dry_run:
            result.created_mosque_website += 1
            continue

        source = MosqueSource(
            id=uuid.uuid4(),
            mosque_id=mosque.id,
            source_type=SourceType.MOSQUE_WEBSITE,
            external_id=f"web-{mosque.id}",
            source_url=homepage,
            publication_policy=SourcePublicationPolicy.UNKNOWN,
            confidence=Confidence.OFFICIAL_IMPORT,
            metadata_={
                "crawl_enabled": True,
                "discovered_by": "website_url_bootstrap",
                "homepage_url": homepage,
                "profile_status": "pending",
                "allowed_crawl_paths": ["/"],
            },
        )
        session.add(source)
        result.created_mosque_website += 1

    if not dry_run:
        await session.flush()
    return result


async def ensure_standard_feed_sources(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> RegisterResult:
    return await ensure_crawl_sources(session, settings=settings)
