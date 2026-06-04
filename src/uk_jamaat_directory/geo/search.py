from __future__ import annotations

import uuid
from dataclasses import dataclass

from geoalchemy2 import Geometry, WKTElement
from geoalchemy2.functions import ST_X, ST_Y, ST_DWithin
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import MosqueStatus
from uk_jamaat_directory.models.core import Mosque


@dataclass(frozen=True)
class MosqueDistanceResult:
    mosque: Mosque
    distance_metres: float
    latitude: float
    longitude: float


def point_wkt(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


async def find_active_mosques_nearby(
    session: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    radius_metres: float,
    limit: int,
) -> list[MosqueDistanceResult]:
    origin = point_wkt(latitude, longitude)
    distance = func.ST_Distance(Mosque.location, origin).label("distance_m")
    location_geometry = cast(Mosque.location, Geometry(geometry_type="POINT", srid=4326))
    latitude_expr = ST_Y(location_geometry).label("latitude")
    longitude_expr = ST_X(location_geometry).label("longitude")

    stmt = (
        select(Mosque, distance, latitude_expr, longitude_expr)
        .where(Mosque.location.is_not(None))
        .where(Mosque.status == MosqueStatus.ACTIVE)
        .where(ST_DWithin(Mosque.location, origin, radius_metres))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MosqueDistanceResult(
            mosque=row[0],
            distance_metres=float(row[1]),
            latitude=float(row[2]),
            longitude=float(row[3]),
        )
        for row in rows
    ]


async def get_active_mosque_by_id(
    session: AsyncSession,
    mosque_id: uuid.UUID,
) -> Mosque | None:
    stmt = select(Mosque).where(Mosque.id == mosque_id).where(Mosque.status == MosqueStatus.ACTIVE)
    return (await session.execute(stmt)).scalar_one_or_none()
