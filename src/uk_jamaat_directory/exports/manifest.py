from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from uk_jamaat_directory.exports.types import ExportDataset, ExportFileInfo

EXPORT_LICENSE_SUMMARY = (
    "Public snapshot rows include only sources with "
    "public_redistribution_allowed. Restricted partner data is excluded."
)


def sha256_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_prefixed(body: bytes) -> str:
    return f"sha256:{sha256_digest(body)}"


def export_manifest_key(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    if stem == "snapshot":
        return "ndjson"
    if stem == "occurrences":
        return "csv"
    return stem


def build_exports_manifest(files: list[ExportFileInfo]) -> dict[str, dict[str, object]]:
    exports: dict[str, dict[str, object]] = {}
    for file_info in files:
        if file_info.name == "manifest.json":
            continue
        exports[export_manifest_key(file_info.name)] = {
            "filename": file_info.name,
            "url": file_info.url,
            "object_key": file_info.object_key,
            "checksum": sha256_prefixed(file_info.body),
            "size_bytes": file_info.size_bytes,
            "content_type": file_info.content_type,
        }
    return exports


def build_manifest_json(dataset: ExportDataset, files: list[ExportFileInfo]) -> bytes:
    payload = {
        "version": dataset.version,
        "schema_version": dataset.schema_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "exports": build_exports_manifest(files),
        "source_counts": {
            "public_redistribution_allowed": dataset.source_counts.public_sources,
            "excluded_restricted": dataset.source_counts.excluded_restricted_sources,
        },
        "license_summary": EXPORT_LICENSE_SUMMARY,
    }
    return (json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n").encode("utf-8")
