from __future__ import annotations

from geoalchemy2 import WKTElement

from uk_jamaat_directory.models.core import Mosque


def set_mosque_point(
    mosque: Mosque,
    latitude: float | None,
    longitude: float | None,
) -> None:
    if latitude is not None and longitude is not None:
        mosque.location = WKTElement(
            f"POINT({longitude} {latitude})",
            srid=4326,
        )
