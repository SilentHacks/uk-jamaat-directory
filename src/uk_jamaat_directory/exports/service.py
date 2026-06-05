from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.exports.checksums import sha256_prefixed
from uk_jamaat_directory.exports.collect import collect_export_dataset, resolve_dataset_version
from uk_jamaat_directory.exports.serialize import build_export_files
from uk_jamaat_directory.exports.types import ExportResult
from uk_jamaat_directory.storage.s3 import S3Storage


async def generate_dataset_exports(
    session: AsyncSession,
    *,
    version_name: str | None = None,
    version_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> ExportResult:
    cfg = settings or get_settings()
    result = ExportResult(version="")

    version = await resolve_dataset_version(
        session,
        version_name=version_name,
        version_id=version_id,
    )
    if version is None:
        result.errors.append("dataset version not found")
        return result

    result.version = version.version
    dataset = await collect_export_dataset(session, version)
    files = build_export_files(
        dataset,
        version=version.version,
        base_url=cfg.export_public_base_url,
        base_prefix=cfg.export_s3_prefix,
    )

    storage = S3Storage(cfg)
    await storage.ensure_bucket()

    exports_manifest: dict[str, dict[str, object]] = {}
    primary_checksum: str | None = None

    for file_info in files:
        await storage.put_bytes(file_info.object_key, file_info.body, file_info.content_type)
        checksum = sha256_prefixed(file_info.body)
        if file_info.name == "snapshot.ndjson":
            primary_checksum = checksum
        if file_info.name == "manifest.json":
            continue
        export_key = _export_manifest_key(file_info.name)
        exports_manifest[export_key] = {
            "url": file_info.url,
            "object_key": file_info.object_key,
            "checksum": checksum,
            "size_bytes": file_info.size_bytes,
            "filename": file_info.name,
            "content_type": file_info.content_type,
        }
        result.files_written += 1

    manifest = dict(version.manifest or {})
    manifest.update(
        {
            "attribution": dataset.attribution,
            "source_counts": {
                "public_redistribution_allowed": dataset.source_counts.public_sources,
                "excluded_restricted": dataset.source_counts.excluded_restricted_sources,
                "total_linked": dataset.source_counts.total_linked_sources,
            },
            "license_summary": (
                "Public snapshot rows include only sources with "
                "public_redistribution_allowed. Restricted partner data is excluded."
            ),
            "exports": exports_manifest,
            "export_generated_at": datetime.now(UTC).isoformat(),
            "mosque_count": len(dataset.mosques),
            "occurrence_count": len(dataset.occurrences),
            "change_event_count": len(dataset.changes),
        }
    )
    version.manifest = manifest
    version.checksum = primary_checksum
    await session.flush()

    result.mosque_count = len(dataset.mosques)
    result.occurrence_count = len(dataset.occurrences)
    result.change_count = len(dataset.changes)
    result.checksum = primary_checksum
    return result


def _export_manifest_key(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0]
    if stem == "snapshot":
        return "ndjson"
    if stem == "occurrences":
        return "csv"
    return stem
