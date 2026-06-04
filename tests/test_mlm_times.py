from __future__ import annotations

from datetime import time

import pytest

from uk_jamaat_directory.ingest.sources.mylocalmasjid.times import parse_hhmm


def test_parse_hhmm_valid() -> None:
    assert parse_hhmm("04:30") == time(4, 30)


def test_parse_hhmm_none_for_empty() -> None:
    assert parse_hhmm("") is None
    assert parse_hhmm(None) is None


def test_parse_hhmm_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="invalid time"):
        parse_hhmm("25:00")
