from __future__ import annotations

import re
from pathlib import Path

import pytest

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    load_all_extractors,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.runner import run_sandbox


def _fixture_html() -> str:
    source = Path(
        "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts"
        "/synthetic_html_table.py"
    ).read_text()
    match = re.search(r"SYNTHETIC_FIXTURE\s*=\s*\"\"\"(.*?)\"\"\"", source, re.S)
    assert match is not None
    return match.group(1)


def _payload(html: str) -> dict:
    return {
        "extractor_key": "synthetic_html_table",
        "source_id": "src-id",
        "mosque_name": "Synthetic Masjid",
        "mosque_id": "mosque-id",
        "source_url": "https://synthetic.example",
        "timezone": "Europe/London",
        "artifacts": {
            "timetable": {
                "target_label": "timetable",
                "target_url": "https://synthetic.example/prayer-timetable",
                "content_type": "text/html",
                "body_hex": html.encode().hex(),
            }
        },
    }


def test_synthetic_extractor_is_registered() -> None:
    keys = {entry.extractor.key for entry in load_all_extractors()}
    assert "synthetic_html_table" in keys


@pytest.mark.asyncio
async def test_sandbox_runs_synthetic_extractor() -> None:
    payload = _payload(_fixture_html())
    result = await run_sandbox(
        payload["extractor_key"], payload, settings=get_settings()
    )
    assert result.ok, result.error
    assert result.result is not None
    assert result.result.rows
    prayers = [row.prayer.value for row in result.result.rows]
    assert "fajr" in prayers
    assert "jumuah" in prayers
    maghrib = next(r for r in result.result.rows if r.prayer.value == "maghrib")
    assert maghrib.evidence.derivation == {
        "type": "relative_offset",
        "base": "start_time",
        "offset_minutes": 5,
        "source_text": "5 minutes",
    }
    assert maghrib.jamaat_time.hour == 21 and maghrib.jamaat_time.minute == 20


@pytest.mark.asyncio
async def test_sandbox_handles_empty_artifact() -> None:
    payload = _payload("")
    payload["artifacts"]["timetable"]["body_hex"] = b"".hex()
    result = await run_sandbox(
        payload["extractor_key"], payload, settings=get_settings()
    )
    assert result.ok
    assert result.result is not None
    assert result.result.rows == []
    assert result.result.no_schedule_reason
