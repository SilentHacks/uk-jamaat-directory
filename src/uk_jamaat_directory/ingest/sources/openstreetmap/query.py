from __future__ import annotations

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


def build_uk_ie_muslim_places_query() -> str:
    return UK_IE_MUSLIM_PLACES_QUERY


def build_gb_muslim_places_query() -> str:
    return build_uk_ie_muslim_places_query()
