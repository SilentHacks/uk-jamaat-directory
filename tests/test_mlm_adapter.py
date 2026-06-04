from __future__ import annotations

from pathlib import Path

import pytest

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.sources.mylocalmasjid.adapter import (
    CsvFeedAdapter,
    JsonFeedAdapter,
    NdjsonFeedAdapter,
    parse_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/mylocalmasjid"


def test_parse_sample_json_export() -> None:
    bundle = parse_file(FIXTURES / "sample_export.json")
    assert len(bundle.mosques) == 2
    assert bundle.mosques[0].external_id == "mlm-synth-001"
    assert bundle.mosques[0].schedules[1].prayer == Prayer.DHUHR
    assert bundle.mosques[0].schedules[1].jamaat_time == "13:20"


def test_json_adapter_normalizes_iqamah_alias() -> None:
    payload = """
    {
      "mosques": [{
        "external_id": "x1",
        "name": "Alias Masjid",
        "schedules": [{
          "date": "2026-06-05",
          "prayer": "asr",
          "iqamah": "16:45"
        }]
      }]
    }
    """
    bundle = JsonFeedAdapter().parse(payload)
    assert bundle.mosques[0].schedules[0].jamaat_time == "16:45"


def test_ndjson_adapter_parses_multiple_records() -> None:
    payload = (
        '{"external_id":"n1","name":"One","schedules":[]}\n'
        '{"external_id":"n2","name":"Two","schedules":[]}\n'
    )
    bundle = NdjsonFeedAdapter().parse(payload)
    assert [mosque.external_id for mosque in bundle.mosques] == ["n1", "n2"]


def test_csv_adapter_groups_rows_by_mosque() -> None:
    payload = (
        "external_id,name,date,prayer,jamaat_time\n"
        "csv-1,CSV Masjid,2026-06-05,fajr,05:00\n"
        "csv-1,CSV Masjid,2026-06-05,maghrib,21:00\n"
    )
    bundle = CsvFeedAdapter().parse(payload)
    assert len(bundle.mosques) == 1
    assert len(bundle.mosques[0].schedules) == 2


def test_unsupported_prayer_raises() -> None:
    payload = """
    {
      "mosques": [{
        "external_id": "bad",
        "name": "Bad",
        "schedules": [{"date": "2026-06-05", "prayer": "tahajjud", "jamaat_time": "03:00"}]
      }]
    }
    """
    with pytest.raises(ValueError, match="unsupported prayer"):
        JsonFeedAdapter().parse(payload)
