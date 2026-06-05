from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, time

from uk_jamaat_directory.exports.manifest import (
    EXPORT_LICENSE_SUMMARY,
    build_exports_manifest,
    sha256_prefixed,
)
from uk_jamaat_directory.exports.serialize import (
    build_changes_ndjson,
    build_export_files,
    build_metadata_json,
    build_occurrences_csv,
    build_snapshot_ndjson,
)
from uk_jamaat_directory.exports.types import ExportDataset, SourceCountSummary
from uk_jamaat_directory.schemas.public import (
    ChangeEventPublic,
    MosqueDetailPublic,
    PublicScheduleOccurrence,
)


def _dataset() -> ExportDataset:
    mosque_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    return ExportDataset(
        version="2026-06-04.1",
        schema_version="1.0",
        published_at=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
        mosques=[
            MosqueDetailPublic(
                directory_mosque_id=mosque_id,
                name="Alpha Masjid",
                country="GB",
                status="active",
            )
        ],
        occurrences=[
            PublicScheduleOccurrence(
                directory_mosque_id=mosque_id,
                date=date(2026, 6, 5),
                prayer="fajr",
                start_time=time(2, 48),
                jamaat_time=time(3, 45),
                session_number=1,
                timezone="Europe/London",
                confidence="partner_import",
                source_type="mylocalmasjid",
                freshness_status="fresh",
                dataset_version="2026-06-04.1",
            )
        ],
        changes=[
            ChangeEventPublic(
                id=1,
                event_type="occurrence_published",
                occurred_at=datetime(2026, 6, 4, 12, 0, tzinfo=UTC),
                directory_mosque_id=mosque_id,
                dataset_version="2026-06-04.1",
                payload={"prayer": "fajr"},
            )
        ],
        attribution=["UK Jamaat Directory", "MyLocalMasjid"],
        source_counts=SourceCountSummary(public_sources=1, excluded_restricted_sources=2),
    )


def test_snapshot_ndjson_is_deterministic() -> None:
    dataset = _dataset()
    first = build_snapshot_ndjson(dataset)
    second = build_snapshot_ndjson(dataset)
    assert first == second
    lines = first.decode("utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["record_type"] == "mosque"
    assert json.loads(lines[1])["record_type"] == "occurrence"


def test_occurrences_csv_has_stable_header_and_row() -> None:
    body = build_occurrences_csv(_dataset())
    text = body.decode("utf-8")
    lines = text.strip().splitlines()
    assert lines[0].startswith("directory_mosque_id,date,prayer")
    assert "fajr" in lines[1]


def test_metadata_and_changes_include_counts() -> None:
    dataset = _dataset()
    metadata = json.loads(build_metadata_json(dataset))
    assert metadata["occurrence_count"] == 1
    assert metadata["source_counts"]["excluded_restricted"] == 2
    assert metadata["license_summary"] == EXPORT_LICENSE_SUMMARY

    changes = build_changes_ndjson(dataset).decode("utf-8").strip().splitlines()
    assert len(changes) == 1
    assert json.loads(changes[0])["event_type"] == "occurrence_published"


def test_checksum_prefix() -> None:
    body = b"example"
    assert sha256_prefixed(body).startswith("sha256:")


def test_manifest_exports_match_file_manifest() -> None:
    dataset = _dataset()
    files = build_export_files(
        dataset,
        version=dataset.version,
        base_url="http://example.org",
    )
    manifest_file = next(file_info for file_info in files if file_info.name == "manifest.json")
    manifest_payload = json.loads(manifest_file.body)
    assert manifest_payload["exports"] == build_exports_manifest(files)


def test_metadata_includes_generated_at() -> None:
    metadata = json.loads(build_metadata_json(_dataset()))
    assert metadata["generated_at"]
