from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import MosqueStatus, SourceType
from uk_jamaat_directory.geo.search import find_active_mosques_nearby, get_active_mosque_by_id
from uk_jamaat_directory.models.core import (
    ChangeEvent,
    DatasetVersion,
    Mosque,
    MosqueAlias,
    MosqueAttribute,
    MosqueSource,
    ScheduleOccurrence,
)
from uk_jamaat_directory.schedules.dataset import (
    PUBLISHED_DATASET_STATUS,
    latest_published_version_id,
)
from uk_jamaat_directory.schemas.public import (
    ChangeFeedResponse,
    MosqueDetailPublic,
    MosqueListResponse,
    NearbyTimeItem,
    NearbyTimesResponse,
    SnapshotResponse,
    TimesResponse,
)
from uk_jamaat_directory.services.mappers import (
    change_event_public,
    mosque_detail,
    mosque_summary,
    schedule_occurrence_from_row,
    snapshot_response,
)
from uk_jamaat_directory.services.public_policy import public_source_filter


def _latest_dataset_filter(session: AsyncSession):
    """Filter occurrences to the latest published dataset version only."""
    return latest_published_version_id(session)


def _crawled_timetable_exists(latest_version_id):
    """Correlated EXISTS: the mosque has at least one published occurrence in the
    latest dataset version that came from a public ``mosque_website`` source.

    This mirrors what the public timetable actually shows (latest published
    dataset + public source policy), restricted to the website-crawl pipeline so
    the filter means "has a successfully crawled, publicly viewable timetable".
    """
    return (
        select(ScheduleOccurrence.id)
        .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
        .where(ScheduleOccurrence.mosque_id == Mosque.id)
        .where(ScheduleOccurrence.dataset_version_id == latest_version_id)
        .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
        .where(public_source_filter())
        .exists()
    )


def _active_mosque_filters(
    *,
    city: str | None = None,
    postcode: str | None = None,
    query: str | None = None,
    crawled_version_id=None,
    crawled_only: bool = False,
):
    filters = [Mosque.status == MosqueStatus.ACTIVE]
    if city:
        filters.append(func.lower(Mosque.city) == city.strip().lower())
    if postcode:
        filters.append(func.upper(Mosque.postcode).like(f"{postcode.strip().upper()}%"))
    if query:
        pattern = f"%{query.strip()}%"
        filters.append(
            or_(
                Mosque.name.ilike(pattern),
                Mosque.normalized_name.ilike(pattern),
            )
        )
    if crawled_only:
        # No published dataset yet means nothing can have a crawled timetable.
        if crawled_version_id is None:
            filters.append(false())
        else:
            filters.append(_crawled_timetable_exists(crawled_version_id))
    return filters


async def list_mosques(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    city: str | None = None,
    postcode: str | None = None,
    crawled_only: bool = False,
) -> MosqueListResponse:
    crawled_version_id = await _latest_dataset_filter(session) if crawled_only else None
    filters = _active_mosque_filters(
        city=city,
        postcode=postcode,
        crawled_only=crawled_only,
        crawled_version_id=crawled_version_id,
    )

    count_stmt = select(func.count()).select_from(Mosque).where(*filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    stmt = select(Mosque).where(*filters).order_by(Mosque.name.asc()).offset(offset).limit(limit)
    mosques = (await session.execute(stmt)).scalars().all()

    return MosqueListResponse(
        items=[mosque_summary(mosque) for mosque in mosques],
        count=total,
        limit=limit,
        offset=offset,
    )


async def search_mosques(
    session: AsyncSession,
    *,
    query: str | None,
    postcode: str | None,
    city: str | None,
    limit: int,
    crawled_only: bool = False,
) -> MosqueListResponse:
    crawled_version_id = await _latest_dataset_filter(session) if crawled_only else None
    filters = _active_mosque_filters(
        query=query,
        postcode=postcode,
        city=city,
        crawled_only=crawled_only,
        crawled_version_id=crawled_version_id,
    )
    stmt = select(Mosque).where(*filters).order_by(Mosque.name.asc()).limit(limit)
    mosques = (await session.execute(stmt)).scalars().all()

    return MosqueListResponse(
        items=[mosque_summary(mosque) for mosque in mosques],
        count=len(mosques),
        limit=limit,
        offset=0,
    )


async def get_mosque(
    session: AsyncSession,
    directory_mosque_id: uuid.UUID,
) -> MosqueDetailPublic | None:
    mosque = await get_active_mosque_by_id(session, directory_mosque_id)
    if mosque is None:
        return None

    aliases = (
        (
            await session.execute(
                select(MosqueAlias)
                .where(MosqueAlias.mosque_id == mosque.id)
                .order_by(MosqueAlias.alias)
            )
        )
        .scalars()
        .all()
    )
    sources = (
        (await session.execute(select(MosqueSource).where(MosqueSource.mosque_id == mosque.id)))
        .scalars()
        .all()
    )
    attributes = (
        await session.execute(select(MosqueAttribute).where(MosqueAttribute.mosque_id == mosque.id))
    ).scalar_one_or_none()

    return mosque_detail(
        mosque, aliases=list(aliases), sources=list(sources), attributes=attributes
    )


async def get_mosque_times(
    session: AsyncSession,
    directory_mosque_id: uuid.UUID,
    *,
    from_date: date,
    to_date: date,
) -> TimesResponse | None:
    mosque = await get_active_mosque_by_id(session, directory_mosque_id)
    if mosque is None:
        return None

    latest_id = await _latest_dataset_filter(session)
    if latest_id is None:
        return TimesResponse(
            directory_mosque_id=directory_mosque_id,
            from_date=from_date,
            to_date=to_date,
            items=[],
        )

    stmt = (
        select(ScheduleOccurrence, MosqueSource, DatasetVersion)
        .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
        .outerjoin(DatasetVersion, ScheduleOccurrence.dataset_version_id == DatasetVersion.id)
        .where(ScheduleOccurrence.mosque_id == directory_mosque_id)
        .where(ScheduleOccurrence.date >= from_date)
        .where(ScheduleOccurrence.date <= to_date)
        .where(ScheduleOccurrence.dataset_version_id == latest_id)
        .where(public_source_filter())
        .order_by(
            ScheduleOccurrence.date, ScheduleOccurrence.prayer, ScheduleOccurrence.session_number
        )
    )
    rows = (await session.execute(stmt)).all()

    return TimesResponse(
        directory_mosque_id=directory_mosque_id,
        from_date=from_date,
        to_date=to_date,
        items=[schedule_occurrence_from_row(row) for row in rows],
    )


async def get_nearby_times(
    session: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    on_date: date,
    limit: int,
) -> NearbyTimesResponse:
    nearby = await find_active_mosques_nearby(
        session,
        latitude=latitude,
        longitude=longitude,
        radius_metres=radius_m,
        limit=limit,
    )
    if not nearby:
        return NearbyTimesResponse(
            date=on_date,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            items=[],
        )

    mosque_ids = [item.mosque.id for item in nearby]
    latest_id = await _latest_dataset_filter(session)
    if latest_id is None:
        return NearbyTimesResponse(
            date=on_date,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
            items=[],
        )

    stmt = (
        select(ScheduleOccurrence, MosqueSource, DatasetVersion, Mosque.name)
        .join(Mosque, ScheduleOccurrence.mosque_id == Mosque.id)
        .join(MosqueSource, ScheduleOccurrence.source_id == MosqueSource.id)
        .outerjoin(DatasetVersion, ScheduleOccurrence.dataset_version_id == DatasetVersion.id)
        .where(ScheduleOccurrence.mosque_id.in_(mosque_ids))
        .where(ScheduleOccurrence.date == on_date)
        .where(ScheduleOccurrence.dataset_version_id == latest_id)
        .where(public_source_filter())
    )
    rows = (await session.execute(stmt)).all()
    occurrences_by_mosque: dict[uuid.UUID, list] = {mosque_id: [] for mosque_id in mosque_ids}
    for row in rows:
        occurrences_by_mosque[row[0].mosque_id].append(row)

    items: list[NearbyTimeItem] = []
    for result in nearby:
        mosque_rows = occurrences_by_mosque.get(result.mosque.id, [])
        for row in mosque_rows:
            items.append(
                NearbyTimeItem(
                    directory_mosque_id=result.mosque.id,
                    mosque_name=row[3],
                    distance_metres=result.distance_metres,
                    occurrence=schedule_occurrence_from_row(row[:3]),
                )
            )

    items.sort(key=lambda item: item.distance_metres)
    return NearbyTimesResponse(
        date=on_date,
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        items=items,
    )


async def get_changes(
    session: AsyncSession,
    *,
    since: int | None,
    limit: int,
) -> ChangeFeedResponse:
    stmt = (
        select(ChangeEvent, DatasetVersion.version)
        .outerjoin(DatasetVersion, ChangeEvent.dataset_version_id == DatasetVersion.id)
        .order_by(ChangeEvent.id.asc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(ChangeEvent.id > since)

    rows = (await session.execute(stmt)).all()
    return ChangeFeedResponse(
        items=[change_event_public(event, dataset_version=version) for event, version in rows],
        count=len(rows),
        limit=limit,
        since=since,
    )


async def get_latest_snapshot(
    session: AsyncSession,
    *,
    format_name: str | None = None,
) -> SnapshotResponse | None:
    stmt = (
        select(DatasetVersion)
        .where(DatasetVersion.status == PUBLISHED_DATASET_STATUS)
        .order_by(DatasetVersion.published_at.desc().nullslast(), DatasetVersion.created_at.desc())
        .limit(1)
    )
    version = (await session.execute(stmt)).scalar_one_or_none()
    if version is None:
        return None
    return snapshot_response(version, format_name=format_name)


async def get_snapshot_by_version(
    session: AsyncSession,
    version_name: str,
    *,
    format_name: str | None = None,
) -> SnapshotResponse | None:
    stmt = select(DatasetVersion).where(DatasetVersion.version == version_name)
    version = (await session.execute(stmt)).scalar_one_or_none()
    if version is None:
        return None
    return snapshot_response(version, format_name=format_name)
