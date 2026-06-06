from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from uk_jamaat_directory.ingest.normalize import normalize_postcode
from uk_jamaat_directory.ingest.sources.openstreetmap.adapter import is_muslim_place
from uk_jamaat_directory.ingest.sources.openstreetmap.schema import OsmPlaceRecord

SkipReason = Literal["no_name", "no_coords", "non_muslim", "invalid_type"]


@dataclass
class MapElementsResult:
    places: list[OsmPlaceRecord] = field(default_factory=list)
    skip_reasons: Counter[SkipReason] = field(default_factory=Counter)


def map_overpass_elements(elements: list[dict[str, Any]]) -> MapElementsResult:
    result = MapElementsResult()
    seen: set[tuple[str, int]] = set()

    for element in elements:
        element_type = element.get("type")
        element_id = element.get("id")
        if not isinstance(element_type, str) or not isinstance(element_id, int):
            result.skip_reasons["invalid_type"] += 1
            continue

        key = (element_type, element_id)
        if key in seen:
            continue
        seen.add(key)

        mapped = map_overpass_element(element)
        if mapped is None:
            continue
        place, skip_reason = mapped
        if skip_reason is not None:
            result.skip_reasons[skip_reason] += 1
            continue
        if place is not None:
            result.places.append(place)

    return result


def map_overpass_element(
    element: dict[str, Any],
    *,
    default_country: str = "GB",
) -> tuple[OsmPlaceRecord | None, SkipReason | None] | None:
    element_type = element.get("type")
    if element_type not in {"node", "way", "relation"}:
        return None

    element_id = element.get("id")
    if not isinstance(element_id, int):
        return None

    tags = element.get("tags")
    if not isinstance(tags, dict):
        tags = {}

    name = _pick_name(tags)
    if not name:
        return None, "no_name"

    latitude, longitude = _pick_coordinates(element)
    if latitude is None or longitude is None:
        return None, "no_coords"

    record = OsmPlaceRecord(
        osm_type=element_type,
        osm_id=element_id,
        name=name,
        aliases=_pick_aliases(tags, primary_name=name),
        address_line1=_pick_address_line1(tags),
        city=_pick_city(tags),
        postcode=normalize_postcode(_tag(tags, "addr:postcode")),
        country=_pick_country(tags, default_country=default_country),
        website_url=_pick_website(tags),
        latitude=latitude,
        longitude=longitude,
        religion=_normalize_tag(_tag(tags, "religion")),
        denomination=_normalize_tag(_tag(tags, "denomination")),
        source_url=f"https://www.openstreetmap.org/{element_type}/{element_id}",
        source_record_updated_at=_parse_datetime(_tag_value(element, "timestamp")),
        osm_version=_int_value(element.get("version")),
        osm_changeset=_int_value(element.get("changeset")),
        osm_user=_tag_value(element, "user"),
    )
    record.website_tags = _pick_website_tags(tags)

    if not is_muslim_place(record):
        return None, "non_muslim"

    return record, None


def _tag(tags: dict[str, Any], key: str) -> str | None:
    return _tag_value(tags, key)


def _tag_value(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_tag(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower() or None


def _pick_name(tags: dict[str, Any]) -> str | None:
    for key in ("name", "name:en", "official_name"):
        value = _tag(tags, key)
        if value:
            return value
    return None


def _split_multi_value(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _pick_aliases(tags: dict[str, Any], *, primary_name: str) -> list[str]:
    aliases: list[str] = []
    seen = {primary_name.casefold()}
    for key in ("alt_name", "official_name", "loc_name"):
        raw = _tag(tags, key)
        if not raw:
            continue
        for alias in _split_multi_value(raw):
            folded = alias.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            aliases.append(alias)
    return aliases


def _pick_address_line1(tags: dict[str, Any]) -> str | None:
    full = _tag(tags, "addr:full")
    if full:
        return full

    housenumber = _tag(tags, "addr:housenumber")
    street = _tag(tags, "addr:street")
    if housenumber and street:
        return f"{housenumber} {street}"
    if street:
        return street
    if housenumber:
        return housenumber

    return _tag(tags, "addr:place")


def _pick_city(tags: dict[str, Any]) -> str | None:
    for key in ("addr:city", "addr:town", "addr:village", "addr:suburb"):
        value = _tag(tags, key)
        if value:
            return value
    return None


def _pick_website(tags: dict[str, Any]) -> str | None:
    for key in ("website", "contact:website"):
        value = _tag(tags, key)
        if not value:
            continue
        if "://" in value:
            return value
        return f"https://{value}"
    return None


def _pick_website_tags(tags: dict[str, Any]) -> list[str]:
    """Collect every website-shaped OSM tag, normalised to a full URL.

    Captures ``website``, ``contact:website``, and ``url``. The single
    canonical :func:`_pick_website` value is added to the schema's
    ``website_url`` field; this list preserves the alternates so a later
    re-check pass can re-discover websites that the original import did
    not promote.
    """
    seen: set[str] = set()
    collected: list[str] = []
    for key in ("website", "contact:website", "url"):
        raw = _tag(tags, key)
        if not raw:
            continue
        value = raw if "://" in raw else f"https://{raw}"
        if value in seen:
            continue
        seen.add(value)
        collected.append(value)
    return collected


def _pick_country(tags: dict[str, Any], *, default_country: str) -> str:
    for key in ("addr:country", "is_in:country_code", "ISO3166-1:alpha2"):
        value = _normalize_tag(_tag(tags, key))
        if value == "ie":
            return "IE"
        if value in {"gb", "uk"}:
            return "GB"
    return default_country


def _pick_coordinates(element: dict[str, Any]) -> tuple[float | None, float | None]:
    element_type = element.get("type")
    if element_type == "node":
        lat = element.get("lat")
        lon = element.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)
        return None, None

    center = element.get("center")
    if isinstance(center, dict):
        lat = center.get("lat")
        lon = center.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return float(lat), float(lon)

    return None, None
