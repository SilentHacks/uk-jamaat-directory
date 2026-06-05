from __future__ import annotations

import json
from pathlib import Path

import pytest

from uk_jamaat_directory.ingest.sources.openstreetmap.adapter import (
    is_muslim_place,
    parse_osm_file,
    validate_osm_bundle,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.exporter import (
    build_bundle_from_overpass_payload,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.mapper import (
    map_overpass_element,
    map_overpass_elements,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.query import (
    build_gb_muslim_places_query,
    build_ie_muslim_places_query,
    build_uk_ie_muslim_places_queries,
    build_uk_ie_muslim_places_query,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/openstreetmap"
OVERPASS_FIXTURE = FIXTURES / "overpass_response.json"


def _load_overpass_fixture() -> dict[str, object]:
    return json.loads(OVERPASS_FIXTURE.read_text(encoding="utf-8"))


def test_build_uk_ie_muslim_places_query_includes_union_filters() -> None:
    query = build_uk_ie_muslim_places_query()
    assert 'area["ISO3166-1"="GB"]' in query
    assert 'area["ISO3166-1"="IE"]' in query
    assert '["religion"="muslim"]' in query
    assert '["denomination"~"^(muslim|sunni|shia|ahmadiyya)$",i]' in query
    assert '["name"~"masjid|mosque|islamic",i]' in query
    assert query.strip().endswith("out center meta;")


def test_build_country_queries_scope_single_area() -> None:
    gb_query = build_gb_muslim_places_query()
    ie_query = build_ie_muslim_places_query()

    assert 'area["ISO3166-1"="GB"]' in gb_query
    assert 'area["ISO3166-1"="IE"]' not in gb_query
    assert 'area["ISO3166-1"="IE"]' in ie_query
    assert 'area["ISO3166-1"="GB"]' not in ie_query


def test_build_uk_ie_muslim_places_queries_returns_gb_and_ie() -> None:
    queries = build_uk_ie_muslim_places_queries()
    assert [region for region, _query in queries] == ["GB", "IE"]


def test_map_overpass_element_website_and_address_normalization() -> None:
    element = {
        "type": "node",
        "id": 910001,
        "lat": 51.5308,
        "lon": -0.0714,
        "tags": {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "name": "Fixture Central Masjid",
            "alt_name": "Central Mosque",
            "addr:housenumber": "10",
            "addr:street": "High Street",
            "addr:city": "London",
            "addr:postcode": "e21aa",
            "website": "https://example.org/central-masjid",
        },
        "timestamp": "2026-01-15T12:34:56Z",
        "version": 7,
        "changeset": 12345,
        "user": "fixture_mapper",
    }
    place, skip_reason = map_overpass_element(element)
    assert skip_reason is None
    assert place is not None
    assert place.website_url == "https://example.org/central-masjid"
    assert place.address_line1 == "10 High Street"
    assert place.city == "London"
    assert place.postcode == "E2 1AA"
    assert place.country == "GB"
    assert place.aliases == ["Central Mosque"]
    assert place.source_record_updated_at is not None
    assert place.source_record_updated_at.isoformat() == "2026-01-15T12:34:56+00:00"
    assert place.osm_version == 7
    assert place.osm_changeset == 12345
    assert place.osm_user == "fixture_mapper"


def test_map_overpass_element_irish_country_and_eircode_normalization() -> None:
    element = {
        "type": "node",
        "id": 910009,
        "lat": 53.3498,
        "lon": -6.2603,
        "tags": {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "name": "Fixture Dublin Mosque",
            "addr:city": "Dublin",
            "addr:postcode": "d02x285",
            "addr:country": "IE",
        },
    }
    place, skip_reason = map_overpass_element(element)
    assert skip_reason is None
    assert place is not None
    assert place.country == "IE"
    assert place.postcode == "D02 X285"


def test_map_overpass_element_prefers_website_over_contact_website() -> None:
    element = {
        "type": "node",
        "id": 910099,
        "lat": 51.5,
        "lon": -0.1,
        "tags": {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "name": "Fixture Website Priority Mosque",
            "website": "https://primary.example.org",
            "contact:website": "https://secondary.example.org",
        },
    }
    place, skip_reason = map_overpass_element(element)
    assert skip_reason is None
    assert place is not None
    assert place.website_url == "https://primary.example.org"


def test_map_overpass_element_contact_website_adds_scheme() -> None:
    element = {
        "type": "node",
        "id": 910002,
        "lat": 53.4808,
        "lon": -2.2426,
        "tags": {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "name": "Fixture Riverside Mosque",
            "contact:website": "riverside-mosque.example.org",
        },
    }
    place, skip_reason = map_overpass_element(element)
    assert skip_reason is None
    assert place is not None
    assert place.website_url == "https://riverside-mosque.example.org"


def test_map_overpass_element_way_and_relation_use_center() -> None:
    way = {
        "type": "way",
        "id": 910003,
        "center": {"lat": 52.4862, "lon": -1.8904},
        "tags": {
            "amenity": "place_of_worship",
            "denomination": "sunni",
            "name": "Fixture Way Masjid",
        },
    }
    relation = {
        "type": "relation",
        "id": 910004,
        "center": {"lat": 53.8008, "lon": -1.5491},
        "tags": {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "name": "Fixture Relation Mosque",
        },
    }

    way_place, way_skip = map_overpass_element(way)
    relation_place, relation_skip = map_overpass_element(relation)

    assert way_skip is None and way_place is not None
    assert way_place.latitude == pytest.approx(52.4862)
    assert way_place.longitude == pytest.approx(-1.8904)

    assert relation_skip is None and relation_place is not None
    assert relation_place.latitude == pytest.approx(53.8008)
    assert relation_place.longitude == pytest.approx(-1.5491)


def test_build_bundle_from_overpass_fixture() -> None:
    payload = _load_overpass_fixture()
    bundle, mapped = build_bundle_from_overpass_payload(payload)

    assert len(bundle.places) == 6
    assert all(is_muslim_place(place) for place in bundle.places)
    assert mapped.skip_reasons["no_name"] == 1
    assert mapped.skip_reasons["no_coords"] == 1
    assert mapped.skip_reasons["non_muslim"] == 1

    external_ids = {place.external_id for place in bundle.places}
    assert external_ids == {
        "node/910001",
        "node/910002",
        "way/910003",
        "relation/910004",
        "node/910005",
        "node/910009",
    }


def test_map_overpass_elements_dedupes_same_type_and_id() -> None:
    payload = _load_overpass_fixture()
    elements = payload["elements"]
    assert isinstance(elements, list)

    mapped = map_overpass_elements(elements)
    assert sum(1 for place in mapped.places if place.external_id == "node/910001") == 1


def test_export_roundtrip_parse_osm_file(tmp_path: Path) -> None:
    payload = _load_overpass_fixture()
    bundle, _mapped = build_bundle_from_overpass_payload(payload)
    validate_osm_bundle(bundle)

    output_path = tmp_path / "osm_export.json"
    output_path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    parsed = parse_osm_file(output_path)
    assert len(parsed.places) == len(bundle.places)
    assert parsed.places[0].external_id == "node/910001"
