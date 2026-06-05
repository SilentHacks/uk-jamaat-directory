from __future__ import annotations

from datetime import datetime
from pathlib import Path

from uk_jamaat_directory.ingest.sources.muslimsinbritain.exporter import (
    apply_mib_detail,
    build_bundle_from_mib_csv,
    parse_mib_detail_page,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import MibMosqueRecord

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


def test_parse_mib_detail_page_extracts_source_updated_and_public_fields() -> None:
    detail = parse_mib_detail_page(
        """
        <html><body>
        <b>Phone:</b> 01224 493764, 07412 324458
        <b>Website:</b> http://www.aberdeenmosque.org
        The MuslimsInBritain.org website cannot guarantee links.
        <b>Capacity:</b> 1200 (including women)
        <b>Theme: </b> Deobandi Deobandi: Influenced by Deoband Madrassah
        <b>Data Accuracy:</b><br/>Full (A): Reasonably recent first-hand knowledge.
        Some of our address lists date back to the late 1970s.
        &nbsp; Source(s): Personal visit; mosque website.
        &nbsp; Last Updated: 11/10/2009
        </body></html>
        """
    )

    assert detail.source_record_updated_at == datetime.fromisoformat("2009-10-11T00:00:00+00:00")
    assert detail.website_url == "http://www.aberdeenmosque.org"
    assert detail.phone == "01224 493764, 07412 324458"
    assert detail.capacity == 1200
    assert detail.theme == "Deobandi"
    assert detail.data_accuracy == "Full (A): Reasonably recent first-hand knowledge"
    assert detail.data_accuracy_code == "A"
    assert detail.data_sources == ["Personal visit", "mosque website"]


def test_apply_mib_detail_updates_record_with_enriched_values() -> None:
    record = MibMosqueRecord(
        external_id="mib-1",
        name="Aberdeen Mosque",
        country="GB",
        latitude=57.1609,
        longitude=-2.1007,
    )
    detail = parse_mib_detail_page(
        """
        Phone: 01224 493764 Website: http://www.aberdeenmosque.org
        Capacity: 1200 Theme: Deobandi Deobandi: text
        Data Accuracy: Full (A): Recent. Some of our address lists date back.
        Source(s): Personal visit. Last Updated: 11/10/2009
        """
    )

    apply_mib_detail(record, detail)

    assert record.source_record_updated_at == datetime.fromisoformat("2009-10-11T00:00:00+00:00")
    assert record.website_url == "http://www.aberdeenmosque.org"
    assert record.phone == "01224 493764"
    assert record.capacity == 1200
    assert record.theme == "Deobandi"
    assert record.data_accuracy_code == "A"
    assert record.data_sources == ["Personal visit"]
