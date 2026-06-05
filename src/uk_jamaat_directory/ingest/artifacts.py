from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import ArtifactStatus
from uk_jamaat_directory.models.core import MosqueSource, SourceArtifact
from uk_jamaat_directory.storage.s3 import S3Storage, artifact_object_key


async def record_fetched_artifact(
    session: AsyncSession,
    source: MosqueSource,
    *,
    fetched_url: str,
    body: bytes,
    content_type: str,
    etag: str | None = None,
    last_modified: str | None = None,
    upload_to_s3: bool = True,
    settings: Settings | None = None,
) -> tuple[SourceArtifact, bool, str]:
    """Persist artifact metadata and optionally upload raw bytes to object storage.

    Returns (artifact, created, content_hash). When content hash already exists for
    this source, returns the existing row with created=False.
    """
    cfg = settings or get_settings()
    content_hash = hashlib.sha256(body).hexdigest()

    existing = await session.scalar(
        select(SourceArtifact).where(
            SourceArtifact.source_id == source.id,
            SourceArtifact.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, False, content_hash

    artifact_id = uuid.uuid4()
    object_key: str | None = None
    if upload_to_s3 and body:
        object_key = artifact_object_key(
            source_id=source.id,
            artifact_id=artifact_id,
            content_hash=content_hash,
            content_type=content_type,
        )
        storage = S3Storage(cfg)
        await storage.ensure_bucket()
        await storage.put_bytes(object_key, body, content_type)

    artifact = SourceArtifact(
        id=artifact_id,
        source_id=source.id,
        fetched_url=fetched_url,
        object_key=object_key,
        content_type=content_type,
        content_hash=content_hash,
        etag=etag,
        last_modified=last_modified,
        status=ArtifactStatus.FETCHED,
        fetched_at=datetime.now(UTC),
    )
    session.add(artifact)
    await session.flush()
    return artifact, True, content_hash


async def latest_artifact_for_source(
    session: AsyncSession,
    source_id: uuid.UUID,
) -> SourceArtifact | None:
    return await session.scalar(
        select(SourceArtifact)
        .where(SourceArtifact.source_id == source_id)
        .order_by(SourceArtifact.fetched_at.desc())
        .limit(1)
    )
