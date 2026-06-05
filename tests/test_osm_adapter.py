from __future__ import annotations

from pathlib import Path

import pytest

from uk_jamaat_directory.ingest.sources.openstreetmap.adapter import (
    osm_to_discovery_record,
    parse_osm_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/openstreetmap"


def test_parse_sample_osm_places() -> None:
    bundle = parse_osm_file(FIXTURES / "sample_places.json")
    assert len(bundle.places) == 2
    assert bundle.places[0].external_id == "node/900001"

    discovery = osm_to_discovery_record(bundle.places[0])
    assert discovery.metadata["latitude"] == 51.5308
    assert discovery.metadata["longitude"] == -0.0714
    assert discovery.metadata["location_precision"] == "osm_geometry"


def test_rejects_non_muslim_place(tmp_path: Path) -> None:
    path_bad = tmp_path / "bad_place.json"
    path_bad.write_text(
        '{"places":[{"osm_type":"node","osm_id":1,"name":"St Example Church","religion":"christian"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a Muslim place"):
        parse_osm_file(path_bad)
