from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.exports.collect import collect_export_dataset
from uk_jamaat_directory.exports.manifest import EXPORT_LICENSE_SUMMARY, build_exports_manifest
from uk_jamaat_directory.exports.serialize import build_export_files
from uk_jamaat_directory.exports.types import ExportResult
from uk_jamaat_directory.schedules.dataset import (
    PUBLISHED_DATASET_STATUS,
    resolve_dataset_version,
)
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
    if version.status != PUBLISHED_DATASET_STATUS:
        result.errors.append("dataset version is not published")
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

    for file_info in files:
        await storage.put_bytes(file_info.object_key, file_info.body, file_info.content_type)

    exports_manifest = build_exports_manifest(files)
    primary_checksum = exports_manifest.get("ndjson", {}).get("checksum")
    result.files_written = sum(1 for file_info in files if file_info.name != "manifest.json")

    manifest = dict(version.manifest or {})
    manifest.update(
        {
            "attribution": dataset.attribution,
            "source_counts": {
                "public_redistribution_allowed": dataset.source_counts.public_sources,
                "excluded_restricted": dataset.source_counts.excluded_restricted_sources,
                "total_linked": dataset.source_counts.total_linked_sources,
            },
            "license_summary": EXPORT_LICENSE_SUMMARY,
            "exports": exports_manifest,
            "export_generated_at": datetime.now(UTC).isoformat(),
            "mosque_count": len(dataset.mosques),
            "occurrence_count": len(dataset.occurrences),
            "change_event_count": len(dataset.changes),
        }
    )
    version.manifest = manifest
    version.checksum = primary_checksum if isinstance(primary_checksum, str) else None
    await session.flush()

    result.mosque_count = len(dataset.mosques)
    result.occurrence_count = len(dataset.occurrences)
    result.change_count = len(dataset.changes)
    result.checksum = primary_checksum if isinstance(primary_checksum, str) else None
    return result
