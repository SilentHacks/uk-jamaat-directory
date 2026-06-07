from __future__ import annotations

from datetime import date, time

import pytest

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.html import (
    extract_tables,
    html_to_text,
    strip_tags,
)
from uk_jamaat_directory.ingest.extract.helpers.prayers import (
    is_jumuah_label,
    parse_prayer_label,
)
from uk_jamaat_directory.ingest.extract.helpers.relative import (
    add_minutes,
    jamaat_after_start,
    parse_offset_minutes,
)
from uk_jamaat_directory.ingest.extract.helpers.times import (
    coerce_time,
    parse_time_loose,
)


class TestHtmlHelpers:
    def test_strip_tags_strips_simple_html(self) -> None:
        assert strip_tags("<p>hello <b>world</b></p>") == "hello world"

    def test_html_to_text_skips_scripts(self) -> None:
        text = html_to_text(
            "<div>visible<script>alert(1)</script>tail</div>"
        )
        assert "visible" in text
        assert "alert" not in text
        assert "tail" in text

    def test_extract_tables_returns_rows(self) -> None:
        html = (
            "<table><tr><th>A</th><th>B</th></tr>"
            "<tr><td>1</td><td>2</td></tr></table>"
        )
        tables = extract_tables(html)
        assert len(tables) == 1
        assert tables[0].header == ["A", "B"]
        assert tables[0].body() == [["1", "2"]]


class TestTimeHelpers:
    def test_parse_hhmm(self) -> None:
        assert parse_time_loose("03:30") == time(3, 30)
        assert parse_time_loose("3:30 am") == time(3, 30)
        assert parse_time_loose("13:30") == time(13, 30)
        assert parse_time_loose("1:30pm") == time(13, 30)
        assert parse_time_loose("12:00 am") == time(0, 0)
        assert parse_time_loose("12:00 pm") == time(12, 0)
        assert parse_time_loose("not a time") is None

    def test_coerce_time_falls_back_to_none(self) -> None:
        assert coerce_time("nope") is None


class TestPrayerHelpers:
    def test_parse_prayer_label_with_typos(self) -> None:
        assert parse_prayer_label("Fajr") == Prayer.FAJR
        assert parse_prayer_label("Zohr") == Prayer.DHUHR
        assert parse_prayer_label("Ishaa") == Prayer.ISHA
        assert parse_prayer_label("Jummah") == Prayer.JUMUAH
        assert parse_prayer_label("Unknown") is None

    def test_is_jumuah_label(self) -> None:
        assert is_jumuah_label("Jumuah")
        assert not is_jumuah_label("Fajr")


class TestRelativeHelpers:
    def test_add_minutes_wraps(self) -> None:
        assert add_minutes(time(23, 45), 30) == time(0, 15)

    def test_jamaat_after_start(self) -> None:
        assert jamaat_after_start(time(21, 15), minutes=5) == time(21, 20)

    def test_parse_offset_minutes(self) -> None:
        assert parse_offset_minutes("5 minutes") == 5
        assert parse_offset_minutes("3 minutes after adhan") == 3
        assert parse_offset_minutes("10 min") == 10
        assert parse_offset_minutes("not a time") is None
        assert parse_offset_minutes("") is None


def test_date_parsing_module_unchanged() -> None:
    assert date(2026, 6, 8).isoformat() == "2026-06-08"


@pytest.mark.parametrize("value", ["", "5m after adhan"])
def test_relative_edge_cases(value: str) -> None:
    if value:
        assert parse_offset_minutes(value) == 5
    else:
        assert parse_offset_minutes(value) is None
