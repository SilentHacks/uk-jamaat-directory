from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uk_jamaat_directory.ingest.normalize import normalize_postcode
from uk_jamaat_directory.ingest.sources.muslimsinbritain.codes import decode_info_code
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import (
    MibImportBundle,
    MibMosqueRecord,
    MibRecordClass,
)

MIB_ATTRIBUTION = "MuslimsInBritain.org"
MIB_BASE_URL = "https://mosques.muslimsinbritain.org"

_LABEL = re.compile(r"^(?P<precision>[*?])?\[(?P<info>[^\]]*)\](?P<body>.*)$")
_ID = re.compile(r"-ID:(?P<id>\d+)\s*$")
_UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
_EIRCODE = re.compile(r"\b[A-Z0-9]{3}\s*[A-Z0-9]{4}\b", re.IGNORECASE)
_PHONE = re.compile(r"(?<!\w)(?:0|\+44|\+353)[\d\s().-]{7,}\d\b")


@dataclass
class MibParsedCsv:
    bundle: MibImportBundle
    skipped: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)


def parse_mib_file(path: Path) -> MibImportBundle:
    payload = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        return parse_mib_csv_text(payload).bundle

    data = json.loads(payload)
    if "mosques" in data:
        return validate_mib_bundle(MibImportBundle.model_validate(data))

    msg = "MiB JSON must contain a 'mosques' array"
    raise ValueError(msg)


def validate_mib_bundle(bundle: MibImportBundle) -> MibImportBundle:
    return MibImportBundle(
        format_version=bundle.format_version,
        exported_at=bundle.exported_at,
        attribution=bundle.attribution,
        mosques=[_validate_record(record.model_dump()) for record in bundle.mosques],
    )


def parse_mib_csv_text(
    text: str,
    *,
    include_multi_faith: bool = False,
    include_defunct: bool = False,
) -> MibParsedCsv:
    result = MibParsedCsv(
        bundle=MibImportBundle(
            format_version="1",
            exported_at=datetime.now(UTC),
            attribution=MIB_ATTRIBUTION,
        )
    )
    reader = csv.reader(text.splitlines())
    for row_number, row in enumerate(reader, start=1):
        try:
            record = mib_record_from_csv_row(row)
        except ValueError as exc:
            result.skipped += 1
            result.skip_reasons[str(exc)] += 1
            continue

        if record.record_class == "defunct" and not include_defunct:
            result.skipped += 1
            result.skip_reasons["defunct"] += 1
            continue
        if record.record_class == "multi_faith" and not include_multi_faith:
            result.skipped += 1
            result.skip_reasons["multi_faith"] += 1
            continue

        try:
            result.bundle.mosques.append(record)
        except ValueError as exc:
            result.skipped += 1
            result.skip_reasons[f"row_{row_number}: {exc}"] += 1
    return result


def mib_record_from_csv_row(row: list[str]) -> MibMosqueRecord:
    if len(row) < 4:
        msg = "missing_columns"
        raise ValueError(msg)

    try:
        longitude = float(row[0])
        latitude = float(row[1])
    except ValueError as exc:
        msg = "invalid_coordinates"
        raise ValueError(msg) from exc

    label = row[2].strip()
    comment = row[3].strip()
    mib_id = _extract_id(comment)
    if mib_id is None:
        msg = "missing_id"
        raise ValueError(msg)

    match = _LABEL.match(label)
    if match is None:
        info = decode_info_code(None)
        name, address_line1, phone = _split_body(label)
        precision = None
    else:
        info = decode_info_code(match.group("info"))
        name, address_line1, phone = _split_body(match.group("body"))
        precision = match.group("precision")
    if not name:
        msg = "missing_name"
        raise ValueError(msg)

    city, county, postcode = _split_comment(comment)
    country = _infer_country(postcode=postcode, latitude=latitude, longitude=longitude)
    record_class = _record_class_from_text(
        default=info.record_class,
        label=label,
        comment=comment,
    )

    return MibMosqueRecord(
        external_id=f"mib-{mib_id}",
        name=name,
        address_line1=address_line1,
        city=city,
        county=county,
        postcode=postcode,
        country=country,
        phone=phone,
        latitude=latitude,
        longitude=longitude,
        source_url=f"{MIB_BASE_URL}/index.php?id={mib_id}",
        detail_page_url=f"{MIB_BASE_URL}/show-mosque.php?id={mib_id}&map",
        record_class=record_class,
        usage=info.usage,
        capacity=info.capacity,
        women_facilities=info.women_facilities,
        location_precision=_location_precision(precision),
        metadata_confidence=info.metadata_confidence,
        theme=info.theme,
        management=info.management,
        attribution=MIB_ATTRIBUTION,
    )


def _validate_record(data: dict[str, Any]) -> MibMosqueRecord:
    record = MibMosqueRecord.model_validate(data)
    if record.country not in {"GB", "IE"}:
        msg = f"record {record.external_id} has unsupported country"
        raise ValueError(msg)
    return record


def _extract_id(comment: str) -> str | None:
    match = _ID.search(comment)
    if match:
        return match.group("id")
    return None


def _split_body(body: str) -> tuple[str, str | None, str | None]:
    cleaned = body.strip()
    phone_match = None
    for match in _PHONE.finditer(cleaned):
        phone_match = match

    phone = None
    if phone_match is not None:
        phone = phone_match.group(0).strip()
        cleaned = cleaned[: phone_match.start()].strip()

    parts = [part.strip() for part in cleaned.split(".") if part.strip()]
    if not parts:
        return "", None, phone
    name = parts[0]
    address_line1 = ". ".join(parts[1:]) or None
    return name, address_line1, phone


def _split_comment(comment: str) -> tuple[str | None, str | None, str | None]:
    without_id = _ID.sub("", comment).strip()
    if not without_id:
        return None, None, None

    city_part, _, postcode_part = without_id.rpartition(",")
    city = city_part.strip() or None
    postcode = _extract_postcode(postcode_part or without_id)
    return city, None, postcode


def _extract_postcode(text: str) -> str | None:
    uk_match = _UK_POSTCODE.search(text)
    if uk_match:
        return normalize_postcode(uk_match.group(0))
    eircode_match = _EIRCODE.search(text)
    if eircode_match:
        return normalize_postcode(eircode_match.group(0))
    return None


def _infer_country(*, postcode: str | None, latitude: float, longitude: float) -> str:
    if postcode is not None and _UK_POSTCODE.fullmatch(postcode):
        return "GB"
    if postcode is not None and _EIRCODE.fullmatch(postcode.replace(" ", "")):
        return "IE"
    if 51.0 <= latitude <= 55.6 and -10.8 <= longitude <= -5.3:
        return "IE"
    return "GB"


def _record_class_from_text(
    *,
    default: MibRecordClass,
    label: str,
    comment: str,
) -> MibRecordClass:
    text = f"{label} {comment}".casefold()
    if "defunct" in text or "not in use" in text:
        return "defunct"
    if "multi" in text:
        return "multi_faith"
    return default


def _location_precision(value: str | None) -> str:
    if value == "*":
        return "precise"
    if value == "?":
        return "approximate"
    return "unknown"
