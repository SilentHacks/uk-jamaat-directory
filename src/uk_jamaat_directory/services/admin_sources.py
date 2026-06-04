from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import Confidence
from uk_jamaat_directory.ingest.policy import parse_publication_policy
from uk_jamaat_directory.models.core import ModerationAction, MosqueSource
from uk_jamaat_directory.schemas.admin import AdminSourceSummary, AdminSourceUpdate
from uk_jamaat_directory.services.errors import SourceNotFoundError


def source_to_summary(source: MosqueSource) -> AdminSourceSummary:
    return AdminSourceSummary(
        source_id=source.id,
        directory_mosque_id=source.mosque_id,
        source_type=source.source_type.value
        if hasattr(source.source_type, "value")
        else str(source.source_type),
        external_id=source.external_id,
        source_url=source.source_url,
        display_name=source.display_name,
        publication_policy=source.publication_policy.value
        if hasattr(source.publication_policy, "value")
        else str(source.publication_policy),
        confidence=source.confidence.value
        if hasattr(source.confidence, "value")
        else str(source.confidence),
        attribution=source.attribution,
        last_seen_at=source.last_seen_at,
    )


async def list_sources(
    session: AsyncSession,
    *,
    mosque_id: uuid.UUID | None = None,
    source_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MosqueSource], int]:
    filters = []
    if mosque_id is not None:
        filters.append(MosqueSource.mosque_id == mosque_id)
    if source_type is not None:
        filters.append(MosqueSource.source_type == source_type)

    count_stmt = select(func.count()).select_from(MosqueSource)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = select(MosqueSource).order_by(MosqueSource.updated_at.desc())
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.offset(offset).limit(limit)
    items = list((await session.execute(stmt)).scalars().all())
    return items, total


async def update_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    payload: AdminSourceUpdate,
    *,
    actor: str,
) -> MosqueSource:
    source = await session.get(MosqueSource, source_id)
    if source is None:
        raise SourceNotFoundError(str(source_id))

    if payload.publication_policy is not None:
        source.publication_policy = parse_publication_policy(payload.publication_policy)
    if payload.confidence is not None:
        source.confidence = Confidence(payload.confidence)
    if payload.source_url is not None:
        source.source_url = payload.source_url
    if payload.display_name is not None:
        source.display_name = payload.display_name
    if payload.attribution is not None:
        source.attribution = payload.attribution

    session.add(
        ModerationAction(
            actor=actor,
            action="update_source",
            entity_type="mosque_source",
            entity_id=source.id,
            metadata_={"mosque_id": str(source.mosque_id) if source.mosque_id else None},
        )
    )
    await session.flush()
    return source
