from __future__ import annotations

from uk_jamaat_directory.ingest.normalize import (
    normalize_city,
    normalize_domain,
    normalize_mosque_name,
    normalize_postcode,
)


def test_normalize_mosque_name_collapses_whitespace() -> None:
    assert normalize_mosque_name("  Central   Masjid  ") == "central masjid"


def test_normalize_postcode_formats_uk() -> None:
    assert normalize_postcode("e21aa") == "E2 1AA"


def test_normalize_domain_strips_www() -> None:
    assert normalize_domain("https://www.example.org/page") == "example.org"


def test_normalize_city() -> None:
    assert normalize_city("  London ") == "london"
