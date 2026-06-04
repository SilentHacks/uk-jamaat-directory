from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.models.core import DatasetVersion

SCHEMA_VERSION = "1.0"
PUBLISHED_DATASET_STATUS = "published"


async def latest_published_version_id(session: AsyncSession):
    version = await get_latest_published_version(session)
    return version.id if version else None


async def get_latest_published_version(session: AsyncSession) -> DatasetVersion | None:
    stmt = (
        select(DatasetVersion)
        .where(DatasetVersion.status == PUBLISHED_DATASET_STATUS)
        .order_by(DatasetVersion.published_at.desc().nullslast(), DatasetVersion.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_published_dataset_version(session: AsyncSession) -> DatasetVersion:
    now = datetime.now(UTC)
    date_prefix = now.date().isoformat()
    existing = (
        await session.execute(
            select(DatasetVersion.version)
            .where(DatasetVersion.version.like(f"{date_prefix}.%"))
            .order_by(DatasetVersion.version.desc())
        )
    ).scalars().all()

    if existing:
        last = existing[0]
        try:
            patch = int(last.rsplit(".", 1)[-1])
        except ValueError:
            patch = len(existing)
        version_name = f"{date_prefix}.{patch + 1}"
    else:
        version_name = f"{date_prefix}.1"

    version = DatasetVersion(
        version=version_name,
        schema_version=SCHEMA_VERSION,
        status=PUBLISHED_DATASET_STATUS,
        published_at=now,
        manifest={"published_at": now.isoformat()},
    )
    session.add(version)
    await session.flush()
    return version
