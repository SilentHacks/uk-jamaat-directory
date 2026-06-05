from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

from uk_jamaat_directory.exports.checksums import sha256_prefixed
from uk_jamaat_directory.exports.types import ExportDataset, ExportFileInfo

OCCURRENCE_CSV_COLUMNS = (
    "directory_mosque_id",
    "date",
    "prayer",
    "start_time",
    "jamaat_time",
    "session_number",
    "session_label",
    "timezone",
    "confidence",
    "source_type",
    "source_url",
    "last_verified_at",
    "freshness_status",
    "dataset_version",
)


def _json_line(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def build_snapshot_ndjson(dataset: ExportDataset) -> bytes:
    lines: list[str] = []
    for mosque in dataset.mosques:
        payload = {"record_type": "mosque", **mosque.model_dump(mode="json")}
        lines.append(_json_line(payload))
    for occurrence in dataset.occurrences:
        payload = {"record_type": "occurrence", **occurrence.model_dump(mode="json")}
        lines.append(_json_line(payload))
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_occurrences_csv(dataset: ExportDataset) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=OCCURRENCE_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for occurrence in dataset.occurrences:
        row = occurrence.model_dump(mode="json")
        writer.writerow({column: row.get(column) for column in OCCURRENCE_CSV_COLUMNS})
    return buffer.getvalue().encode("utf-8")


def build_changes_ndjson(dataset: ExportDataset) -> bytes:
    lines = [_json_line(change.model_dump(mode="json")) for change in dataset.changes]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_metadata_json(dataset: ExportDataset) -> bytes:
    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "version": dataset.version,
        "schema_version": dataset.schema_version,
        "published_at": dataset.published_at.isoformat() if dataset.published_at else None,
        "generated_at": generated_at,
        "mosque_count": len(dataset.mosques),
        "occurrence_count": len(dataset.occurrences),
        "change_event_count": len(dataset.changes),
        "source_counts": {
            "public_redistribution_allowed": dataset.source_counts.public_sources,
            "excluded_restricted": dataset.source_counts.excluded_restricted_sources,
            "total_linked": dataset.source_counts.total_linked_sources,
        },
        "license_summary": (
            "Public snapshot rows include only sources with "
            "public_redistribution_allowed. Restricted partner data is excluded."
        ),
        "attribution": dataset.attribution,
    }
    return (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")


def build_attribution_txt(dataset: ExportDataset) -> bytes:
    lines = dataset.attribution or ["UK Jamaat Directory"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_export_files(
    dataset: ExportDataset,
    *,
    version: str,
    base_url: str,
    base_prefix: str = "exports",
) -> list[ExportFileInfo]:
    from uk_jamaat_directory.exports.paths import export_object_key, export_public_url

    builders: list[tuple[str, str, str, bytes]] = [
        ("snapshot.ndjson", "application/x-ndjson", "ndjson", build_snapshot_ndjson(dataset)),
        ("occurrences.csv", "text/csv", "csv", build_occurrences_csv(dataset)),
        ("changes.ndjson", "application/x-ndjson", "changes", build_changes_ndjson(dataset)),
        ("metadata.json", "application/json", "metadata", build_metadata_json(dataset)),
        ("attribution.txt", "text/plain", "attribution", build_attribution_txt(dataset)),
    ]

    files: list[ExportFileInfo] = []
    for filename, content_type, _export_name, body in builders:
        files.append(
            ExportFileInfo(
                name=filename,
                object_key=export_object_key(version, filename, base_prefix=base_prefix),
                url=export_public_url(
                    version,
                    filename,
                    base_url=base_url,
                    base_prefix=base_prefix,
                ),
                content_type=content_type,
                body=body,
            )
        )

    manifest_body = build_manifest_json(dataset, files)
    files.append(
        ExportFileInfo(
            name="manifest.json",
            object_key=export_object_key(version, "manifest.json", base_prefix=base_prefix),
            url=export_public_url(
                version,
                "manifest.json",
                base_url=base_url,
                base_prefix=base_prefix,
            ),
            content_type="application/json",
            body=manifest_body,
        )
    )
    return files


def build_manifest_json(dataset: ExportDataset, files: list[ExportFileInfo]) -> bytes:
    exports: dict[str, dict[str, object]] = {}
    for file_info in files:
        if file_info.name == "manifest.json":
            continue
        export_key = file_info.name.rsplit(".", 1)[0]
        if export_key == "snapshot":
            export_key = "ndjson"
        elif export_key == "occurrences":
            export_key = "csv"
        exports[export_key] = {
            "filename": file_info.name,
            "url": file_info.url,
            "object_key": file_info.object_key,
            "checksum": sha256_prefixed(file_info.body),
            "size_bytes": file_info.size_bytes,
            "content_type": file_info.content_type,
        }

    payload = {
        "version": dataset.version,
        "schema_version": dataset.schema_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "exports": exports,
        "source_counts": {
            "public_redistribution_allowed": dataset.source_counts.public_sources,
            "excluded_restricted": dataset.source_counts.excluded_restricted_sources,
        },
        "license_summary": (
            "Public snapshot rows include only sources with public_redistribution_allowed."
        ),
    }
    return (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
