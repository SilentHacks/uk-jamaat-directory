from __future__ import annotations

_COUNTRY_MUSLIM_PLACES_QUERY = """\
[out:json][timeout:{timeout}];
area["ISO3166-1"="{iso}"][admin_level=2]->.{area};
(
  node["amenity"="place_of_worship"]["religion"="muslim"](area.{area});
  way["amenity"="place_of_worship"]["religion"="muslim"](area.{area});
  relation["amenity"="place_of_worship"]["religion"="muslim"](area.{area});
  node["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.{area});
  way["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.{area});
  relation["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.{area});
  node["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.{area});
  way["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.{area});
  relation["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.{area});
);
out center tags;
"""

UK_IE_MUSLIM_PLACES_QUERY = """\
[out:json][timeout:180];
area["ISO3166-1"="GB"][admin_level=2]->.gb;
area["ISO3166-1"="IE"][admin_level=2]->.ie;
(
  node["amenity"="place_of_worship"]["religion"="muslim"](area.gb);
  way["amenity"="place_of_worship"]["religion"="muslim"](area.gb);
  relation["amenity"="place_of_worship"]["religion"="muslim"](area.gb);
  node["amenity"="place_of_worship"]["religion"="muslim"](area.ie);
  way["amenity"="place_of_worship"]["religion"="muslim"](area.ie);
  relation["amenity"="place_of_worship"]["religion"="muslim"](area.ie);
  node["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.gb);
  way["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.gb);
  relation["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.gb);
  node["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.ie);
  way["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.ie);
  relation["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.ie);
  node["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.gb);
  way["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.gb);
  relation["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.gb);
  node["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.ie);
  way["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.ie);
  relation["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.ie);
);
out center tags;
"""


def _build_country_muslim_places_query(*, iso: str, area: str, timeout: int = 240) -> str:
    return _COUNTRY_MUSLIM_PLACES_QUERY.format(iso=iso, area=area, timeout=timeout)


def build_gb_muslim_places_query() -> str:
    return _build_country_muslim_places_query(iso="GB", area="gb")


def build_ie_muslim_places_query() -> str:
    return _build_country_muslim_places_query(iso="IE", area="ie")


def build_uk_ie_muslim_places_query() -> str:
    return UK_IE_MUSLIM_PLACES_QUERY


def build_uk_ie_muslim_places_queries() -> list[tuple[str, str]]:
    """Per-country queries used for live export (avoids combined Overpass timeouts)."""
    return [
        ("GB", build_gb_muslim_places_query()),
        ("IE", build_ie_muslim_places_query()),
    ]
