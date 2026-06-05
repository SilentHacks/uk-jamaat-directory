from __future__ import annotations

from pathlib import Path

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.standard_feed import extract_standard_feed

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/crawl"


def test_extract_valid_standard_feed() -> None:
    body = (FIXTURES / "standard_feed_valid.json").read_bytes()
    result = extract_standard_feed(body)
    assert result.extractor_version == "standard-feed-v1"
    assert len(result.rows) == 36
    assert result.rows[0].prayer == Prayer.FAJR
    jumuah_rows = [row for row in result.rows if row.prayer == Prayer.JUMUAH]
    assert len(jumuah_rows) == 1
    assert jumuah_rows[0].date.isoformat() == "2026-06-05"


def test_extract_invalid_standard_feed_warns() -> None:
    body = (FIXTURES / "standard_feed_invalid.json").read_bytes()
    result = extract_standard_feed(body)
    assert result.rows == []
    assert result.warnings
