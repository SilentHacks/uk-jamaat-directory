from __future__ import annotations

from uk_jamaat_directory.ingest.normalize import normalize_mosque_name


def test_normalize_mosque_name_collapses_whitespace() -> None:
    assert normalize_mosque_name("  Central   Masjid  ") == "central masjid"
