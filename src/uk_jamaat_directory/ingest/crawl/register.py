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
from uk_jamaat_directory.ingest.normalize import normalize_domain
from uk_jamaat_directory.models.core import Mosque, MosqueSource, SourceHealth


@dataclass
class RegisterResult:
    created: int = 0
    skipped_existing: int = 0
    skipped_mlm: int = 0
    skipped_no_domain: int = 0
    errors: list[str] = field(default_factory=list)


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


async def ensure_standard_feed_sources(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> RegisterResult:
    cfg = settings or get_settings()
    result = RegisterResult()

    mosques = (
        (
            await session.execute(
                select(Mosque)
                .where(Mosque.status == MosqueStatus.ACTIVE)
                .where(Mosque.website_url.is_not(None))
            )
        )
        .scalars()
        .all()
    )

    for mosque in mosques:
        domain = normalize_domain(mosque.website_url)
        if domain is None:
            result.skipped_no_domain += 1
            continue

        existing = await session.scalar(
            select(MosqueSource).where(
                MosqueSource.source_type == SourceType.STANDARD_FEED,
                MosqueSource.external_id == domain,
            )
        )
        if existing is not None:
            result.skipped_existing += 1
            continue

        if await _has_recent_mlm_source(session, mosque.id, settings=cfg):
            result.skipped_mlm += 1
            continue

        feed_url = f"https://{domain}{cfg.standard_feed_path}"
        source = MosqueSource(
            id=uuid.uuid4(),
            mosque_id=mosque.id,
            source_type=SourceType.STANDARD_FEED,
            external_id=domain,
            source_url=feed_url,
            publication_policy=SourcePublicationPolicy.UNKNOWN,
            confidence=Confidence.OFFICIAL_IMPORT,
            metadata_={
                "crawl_enabled": True,
                "discovered_by": "website_url_bootstrap",
            },
        )
        session.add(source)
        result.created += 1

    await session.flush()
    return result
