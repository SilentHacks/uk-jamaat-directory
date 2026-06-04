from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from io import StringIO
from pathlib import Path
from typing import Any

from uk_jamaat_directory.ingest.sources.mylocalmasjid.schema import (
    JAMAAT_TIME_ALIASES,
    MyLocalMasjidImportBundle,
    MyLocalMasjidMosqueRecord,
    MyLocalMasjidScheduleRow,
)


class ImportFormat(StrEnum):
    JSON = "json"
    NDJSON = "ndjson"
    CSV = "csv"


class MyLocalMasjidAdapter(ABC):
    """Parse MyLocalMasjid-shaped payloads without coupling to a fetch mechanism."""

    format: ImportFormat

    @abstractmethod
    def parse(self, raw: str | bytes) -> MyLocalMasjidImportBundle:
        raise NotImplementedError


class JsonFeedAdapter(MyLocalMasjidAdapter):
    format = ImportFormat.JSON

    def parse(self, raw: str | bytes) -> MyLocalMasjidImportBundle:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(text)
        return _bundle_from_payload(payload)


class NdjsonFeedAdapter(MyLocalMasjidAdapter):
    format = ImportFormat.NDJSON

    def parse(self, raw: str | bytes) -> MyLocalMasjidImportBundle:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        mosques: list[MyLocalMasjidMosqueRecord] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            mosques.append(_mosque_from_dict(record))
        return MyLocalMasjidImportBundle(mosques=mosques)


class CsvFeedAdapter(MyLocalMasjidAdapter):
    """Import mosque schedule rows from a flat CSV export."""

    format = ImportFormat.CSV

    def parse(self, raw: str | bytes) -> MyLocalMasjidImportBundle:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        reader = csv.DictReader(StringIO(text))
        grouped: dict[str, dict[str, Any]] = {}
        for row in reader:
            external_id = (row.get("external_id") or row.get("mosque_id") or "").strip()
            if not external_id:
                msg = "CSV row missing external_id or mosque_id"
                raise ValueError(msg)
            bucket = grouped.setdefault(
                external_id,
                {
                    "external_id": external_id,
                    "name": (row.get("name") or row.get("mosque_name") or external_id).strip(),
                    "city": _optional(row, "city"),
                    "postcode": _optional(row, "postcode"),
                    "profile_url": _optional(row, "profile_url"),
                    "linkback_url": _optional(row, "linkback_url"),
                    "schedules": [],
                },
            )
            schedule = _schedule_from_csv_row(row)
            bucket["schedules"].append(schedule)
        mosques = [MyLocalMasjidMosqueRecord.model_validate(item) for item in grouped.values()]
        return MyLocalMasjidImportBundle(mosques=mosques)


def detect_adapter(path: Path, *, format_hint: ImportFormat | None = None) -> MyLocalMasjidAdapter:
    if format_hint is not None:
        return _adapter_for_format(format_hint)
    suffix = path.suffix.lower()
    if suffix == ".ndjson":
        return NdjsonFeedAdapter()
    if suffix == ".csv":
        return CsvFeedAdapter()
    return JsonFeedAdapter()


def parse_file(path: Path, *, format_hint: ImportFormat | None = None) -> MyLocalMasjidImportBundle:
    adapter = detect_adapter(path, format_hint=format_hint)
    return adapter.parse(path.read_bytes())


def _adapter_for_format(fmt: ImportFormat) -> MyLocalMasjidAdapter:
    if fmt == ImportFormat.JSON:
        return JsonFeedAdapter()
    if fmt == ImportFormat.NDJSON:
        return NdjsonFeedAdapter()
    if fmt == ImportFormat.CSV:
        return CsvFeedAdapter()
    msg = f"unsupported import format: {fmt}"
    raise ValueError(msg)


def _bundle_from_payload(payload: dict[str, Any]) -> MyLocalMasjidImportBundle:
    if "mosques" in payload:
        mosques = [_mosque_from_dict(item) for item in payload["mosques"]]
        exported_at = _parse_exported_at(payload.get("exported_at"))
        return MyLocalMasjidImportBundle(
            format_version="1",
            exported_at=exported_at,
            source_label=str(payload.get("source_label", "mylocalmasjid")),
            mosques=mosques,
        )
    if "external_id" in payload and "name" in payload:
        return MyLocalMasjidImportBundle(mosques=[_mosque_from_dict(payload)])
    msg = "JSON payload must contain 'mosques' or a single mosque record"
    raise ValueError(msg)


def _mosque_from_dict(data: dict[str, Any]) -> MyLocalMasjidMosqueRecord:
    schedules = data.get("schedules") or data.get("timetable") or []
    normalized_schedules = [_schedule_from_dict(item) for item in schedules]
    mosque_data = {**data, "schedules": normalized_schedules}
    return MyLocalMasjidMosqueRecord.model_validate(mosque_data)


def _schedule_from_dict(data: dict[str, Any]) -> MyLocalMasjidScheduleRow:
    normalized = dict(data)
    for alias in JAMAAT_TIME_ALIASES:
        if alias in normalized and "jamaat_time" not in normalized:
            normalized["jamaat_time"] = normalized.pop(alias)
            break
    return MyLocalMasjidScheduleRow.model_validate(normalized)


def _schedule_from_csv_row(row: dict[str, str | None]) -> dict[str, Any]:
    prayer = (row.get("prayer") or "").strip()
    date_value = (row.get("date") or "").strip()
    if not prayer or not date_value:
        msg = "CSV schedule row requires date and prayer columns"
        raise ValueError(msg)
    jamaat_time = None
    for column in JAMAAT_TIME_ALIASES:
        if row.get(column):
            jamaat_time = row[column]
            break
    return {
        "date": date_value,
        "prayer": prayer,
        "start_time": row.get("start_time"),
        "jamaat_time": jamaat_time,
        "session_number": int((row.get("session_number") or "1").strip() or "1"),
        "session_label": row.get("session_label"),
        "timezone": (row.get("timezone") or "Europe/London").strip(),
    }


def _optional(row: dict[str, str | None], key: str) -> str | None:
    value = row.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_exported_at(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
