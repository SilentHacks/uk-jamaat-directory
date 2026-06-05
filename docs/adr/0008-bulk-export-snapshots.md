# 0008: Bulk Export Snapshots

## Status

Accepted.

## Context

Public API clients and downstream consumers such as Sirat need reproducible full snapshots and change feeds. Dataset versions already track published occurrences, but export files and manifest metadata were not generated automatically.

## Decision

1. **Explicit export generation** — `generate-exports` CLI and a daily Celery task build files for a published `dataset_version`. Publication does not implicitly create export blobs.

2. **Public-safe rows only** — exports include active mosques and occurrences from sources with `public_redistribution_allowed` only. Restricted sources are counted in manifest metadata but excluded from snapshot rows.

3. **Deterministic serialization** — `snapshot.ndjson` and `occurrences.csv` use stable sorting and JSON key ordering so repeated runs with the same database state produce identical bytes. `metadata.json` and `manifest.json` include `generated_at` timestamps and are not byte-identical across runs.

4. **Published versions only** — export generation rejects dataset versions that are not `published`, including explicit CLI `--version` / `--version-id` lookups.

5. **Object storage** — export files live in the configured S3/MinIO bucket under `exports/{version}/` with checksums and public URLs recorded in `dataset_versions.manifest.exports`. Upload failures leave the database manifest unchanged; re-running export generation overwrites objects for the same version.

6. **Artifact set per version** — `snapshot.ndjson` (mosques + occurrences), `occurrences.csv`, `changes.ndjson`, `metadata.json`, `attribution.txt`, and `manifest.json`.

7. **Opt-in automation** — `EXPORT_ENABLED` defaults to `false`; Celery beat schedules daily export generation only when explicitly enabled.

## Consequences

- `/v1/snapshots/*` returns manifest entries after `generate-exports` runs.
- Operators run export generation after publish (or rely on Celery beat when enabled).
- `EXPORT_BASE_URL` must point at the public object endpoint (or CDN) that serves export blobs; the API does not proxy `/exports/*`. When unset, `PUBLIC_BASE_URL` is used as a fallback.
