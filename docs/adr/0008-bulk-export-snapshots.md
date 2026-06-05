# 0008: Bulk Export Snapshots

## Status

Accepted.

## Context

Public API clients and downstream consumers such as Sirat need reproducible full snapshots and change feeds. Dataset versions already track published occurrences, but export files and manifest metadata were not generated automatically.

## Decision

1. **Explicit export generation** — `generate-exports` CLI and a daily Celery task build files for a published `dataset_version`. Publication does not implicitly create export blobs.

2. **Public-safe rows only** — exports include active mosques and occurrences from sources with `public_redistribution_allowed` only. Restricted sources are counted in manifest metadata but excluded from snapshot rows.

3. **Deterministic serialization** — NDJSON and CSV outputs use stable sorting and JSON key ordering so repeated runs with the same database state produce identical bytes.

4. **Object storage** — export files live in the configured S3/MinIO bucket under `exports/{version}/` with checksums and public URLs recorded in `dataset_versions.manifest.exports`.

5. **Artifact set per version** — `snapshot.ndjson` (mosques + occurrences), `occurrences.csv`, `changes.ndjson`, `metadata.json`, `attribution.txt`, and `manifest.json`.

## Consequences

- `/v1/snapshots/*` returns manifest entries after `generate-exports` runs.
- Operators run export generation after publish (or rely on Celery beat).
- Download URLs assume `EXPORT_BASE_URL` or `PUBLIC_BASE_URL` until a dedicated CDN or signed-URL service is added.
