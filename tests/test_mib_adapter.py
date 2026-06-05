from __future__ import annotations

from pathlib import Path

from uk_jamaat_directory.ingest.sources.muslimsinbritain.adapter import (
    mib_record_from_csv_row,
    parse_mib_csv_text,
    parse_mib_file,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.codes import decode_info_code

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/muslimsinbritain"


def test_decode_info_code_extracts_capacity_facilities_theme_and_management() -> None:
    info = decode_info_code("250WDeobBang")
    assert info.capacity == 250
    assert info.women_facilities == "yes"
    assert info.usage == "full_time"
    assert info.theme == "Deobandi"
    assert info.management == "Bangladeshi"


def test_decode_info_code_handles_low_confidence_irregular_usage() -> None:
    info = decode_info_code("?40Irreg")
    assert info.capacity == 40
    assert info.metadata_confidence == "low"
    assert info.usage == "irregular"
    assert info.record_class == "prayer_room"


def test_mib_record_from_csv_row_maps_live_shape() -> None:
    record = mib_record_from_csv_row(
        [
            "-0.0714",
            "51.5308",
            "*[250WDeobBang]Synthetic OSM Central Masjid. 10 High Street. 020 7000 0000",
            "London,E2 1AA-ID:1",
        ]
    )
    assert record.external_id == "mib-1"
    assert record.name == "Synthetic OSM Central Masjid"
    assert record.address_line1 == "10 High Street"
    assert record.phone == "020 7000 0000"
    assert record.postcode == "E2 1AA"
    assert record.country == "GB"
    assert record.source_url == "https://mosques.muslimsinbritain.org/index.php?id=1"


def test_mib_record_from_csv_row_detects_irish_eircode() -> None:
    record = mib_record_from_csv_row(
        [
            "-6.2603",
            "53.3498",
            "*[300ArabArab]Synthetic Dublin Mosque. 1 Example Road. +353 1 555 0100",
            "Dublin,D02 X285-ID:2",
        ]
    )
    assert record.country == "IE"
    assert record.postcode == "D02 X285"
    assert record.phone == "+353 1 555 0100"


def test_mib_record_from_csv_row_accepts_label_without_info_code() -> None:
    record = mib_record_from_csv_row(
        [
            "-0.10",
            "51.50",
            "Plain Label Mosque. 2 Example Street. 020 7000 0001",
            "London,E1 1AA-ID:99",
        ]
    )
    assert record.external_id == "mib-99"
    assert record.name == "Plain Label Mosque"
    assert record.capacity is None
    assert record.metadata_confidence == "unknown"


def test_parse_mib_csv_text_filters_multi_faith_and_defunct() -> None:
    parsed = parse_mib_csv_text((FIXTURES / "raw_poi_sample.csv").read_text(encoding="utf-8"))
    assert len(parsed.bundle.mosques) == 3
    assert parsed.skipped == 2
    assert parsed.skip_reasons["multi_faith"] == 1
    assert parsed.skip_reasons["defunct"] == 1


def test_parse_mib_file_reads_normalized_bundle() -> None:
    bundle = parse_mib_file(FIXTURES / "sample_export.json")
    assert len(bundle.mosques) == 3
    assert {record.country for record in bundle.mosques} == {"GB", "IE"}
