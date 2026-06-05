from __future__ import annotations

GB_MUSLIM_PLACES_QUERY = """\
[out:json][timeout:180];
area["ISO3166-1"="GB"][admin_level=2]->.gb;
(
  node["amenity"="place_of_worship"]["religion"="muslim"](area.gb);
  way["amenity"="place_of_worship"]["religion"="muslim"](area.gb);
  relation["amenity"="place_of_worship"]["religion"="muslim"](area.gb);
  node["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.gb);
  way["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.gb);
  relation["amenity"="place_of_worship"]["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i](area.gb);
  node["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.gb);
  way["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.gb);
  relation["amenity"="place_of_worship"]["name"~"masjid|mosque|islamic",i](area.gb);
);
out center tags;
"""


def build_gb_muslim_places_query() -> str:
    return GB_MUSLIM_PLACES_QUERY
