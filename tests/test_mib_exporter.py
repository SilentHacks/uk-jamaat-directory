from __future__ import annotations

from pathlib import Path

from uk_jamaat_directory.ingest.sources.muslimsinbritain.exporter import (
    build_bundle_from_mib_csv,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/muslimsinbritain"


def test_build_bundle_from_mib_csv_uses_full_uk_ie_scope() -> None:
    raw = (FIXTURES / "raw_poi_sample.csv").read_text(encoding="utf-8")
    parsed = build_bundle_from_mib_csv(raw)

    assert len(parsed.bundle.mosques) == 3
    assert {record.country for record in parsed.bundle.mosques} == {"GB", "IE"}
    assert parsed.skip_reasons["multi_faith"] == 1
    assert parsed.skip_reasons["defunct"] == 1


def test_build_bundle_from_mib_csv_preserves_stable_source_ids() -> None:
    raw = (FIXTURES / "raw_poi_sample.csv").read_text(encoding="utf-8")
    parsed = build_bundle_from_mib_csv(raw)

    assert [record.external_id for record in parsed.bundle.mosques] == [
        "mib-1",
        "mib-2",
        "mib-3",
    ]
