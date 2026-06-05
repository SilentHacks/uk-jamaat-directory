from __future__ import annotations

import json

from pydantic import ValidationError

from uk_jamaat_directory.ingest.extract.standard_feed.schema import StandardFeedDocument
from uk_jamaat_directory.ingest.extract.types import ExtractedScheduleRow, ExtractResult
from uk_jamaat_directory.schedules.parse import parse_hhmm

EXTRACTOR_VERSION = "standard-feed-v1"


def extract_standard_feed(body: bytes) -> ExtractResult:
    result = ExtractResult(extractor_version=EXTRACTOR_VERSION)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        result.warnings.append(f"invalid json: {exc}")
        return result

    try:
        document = StandardFeedDocument.model_validate(payload)
    except ValidationError as exc:
        result.warnings.append(f"schema validation failed: {exc}")
        return result

    timezone = document.timezone
    for index, row in enumerate(document.times):
        try:
            jamaat = parse_hhmm(row.jamaat_time)
            if jamaat is None:
                result.warnings.append(f"row {index}: missing jamaat_time")
                continue
            start = parse_hhmm(row.start_time) if row.start_time else None
            result.rows.append(
                ExtractedScheduleRow(
                    date=row.date,
                    prayer=row.prayer,
                    jamaat_time=jamaat,
                    start_time=start,
                    session_number=row.session_number,
                    session_label=row.session_label,
                    timezone=timezone,
                )
            )
        except ValueError as exc:
            result.warnings.append(f"row {index}: {exc}")

    return result
