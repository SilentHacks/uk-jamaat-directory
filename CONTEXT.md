# UK Jamaat Directory Context

## Product Boundary

The UK Jamaat Directory is a public data utility. It owns canonical UK mosque identity records, linked source provenance, jamaat timetable occurrences, freshness status, public read APIs, contribution workflows, and bulk exports.

Sirat is a private journey-planning consumer. Sirat should sync Directory data into its own local read model and must not contain the Directory crawler, extraction, moderation, or publication infrastructure.

## Domain Language

- **Directory**: this public data service.
- **Directory Mosque ID**: stable public ID assigned by the Directory.
- **Source**: an external origin such as MyLocalMasjid, OSM, mosque website, standard feed, community submission, manual/admin entry, or partner feed.
- **Discovery Lead**: private admin-only hint (for example from Google search) used to find a missing mosque. Not public provenance.
- **Source Artifact**: raw fetched evidence such as HTML, PDF, image, JSON, or CSV. Artifacts are private operational data.
- **Schedule Candidate**: extracted or imported proposed timing pending validation and publication.
- **Published Occurrence**: public normalized row for one mosque, one date, one prayer, and one jamaat session.
- **Prayer Start**: adhan or prayer start time.
- **Jamaat**: congregation time. Internal canonical spelling is `jamaat`; import aliases include `jamat`, `iqamah`, and `iqama`.
- **Confidence**: public trust tier. Initial values are `verified`, `official_import`, `partner_import`, `community`, and `calculated`.
- **Freshness Status**: public coverage state. Initial values are `fresh`, `stale`, `missing_today`, `missing_next_7_days`, `source_failed`, and `needs_review`.

## Source Policy

Every source must carry a publication policy:

- `public_redistribution_allowed`: normalized facts may appear in public APIs and exports.
- `private_use_only`: operational use only; must not appear in public exports.
- `unknown`: cannot publish until clarified.
- `blocked`: must not ingest or publish.

MyLocalMasjid is the preferred primary source because it maintains broad UK mosque coverage. It still requires explicit permission before normalized MLM-derived timetable data can be redistributed publicly.

## Publication Invariants

- Every published jamaat row has source provenance, confidence, freshness, and dataset version.
- Unknown or restricted partner data never enters public snapshots.
- Raw artifacts, private contact details, and moderation notes are never public export fields.
- AI extraction can create candidates only. It does not directly publish rows until benchmarked and explicitly enabled.
- The Directory API is versioned under `/v1`.
- Sirat and other consumers should rely on snapshots and change feeds, not live request-path coupling.

## Implementation Status

As of the current codebase (Phases 0–4):

- **Done:** service scaffold, PostGIS schema, public read API (`/v1/mosques`, `/v1/times/nearby`, `/v1/changes`, `/v1/snapshots`), source publication filtering on reads, OpenAPI/JSON Schema exports in `docs/api/`.
- **Done (Phase 5):** MyLocalMasjid adapter and `import-mlm` / `report-mlm` CLI; imports create private artifacts, sources, and `schedule_candidates` regardless of publication policy.
- **Done (Phase 6):** Shared discovery matching, OSM fixture import (`import-osm`), MLM link-before-create, admin mosque identity APIs, community mosque submissions, private Google discovery leads (admin-only).
- **Done (Phase 7):** Deterministic schedule validation, explicit `validate-candidates` / `publish-candidates` CLI, dataset-versioned occurrences, change events on publish, freshness recompute, public reads filtered to latest published dataset.
- **Done (Phase 8):** Admin candidate/source moderation APIs, coverage and source-health reporting, public corrections/schedule submissions/claims with private contact handling.
- **Done (Phase 9 slice 9.1):** Standard feed crawl pipeline (fetch → MinIO artifact → extract → candidates), Celery tasks, crawl CLI. HTML/PDF/OCR/AI/Playwright deferred.
- **Done (Phase 10):** Bulk export generation (`generate-exports` CLI, Celery task), NDJSON/CSV/changes/metadata files in object storage, manifest checksums on `dataset_versions`.
- **Done (Phase 11):** `docker-compose.vps.yml` production stack, Caddy TLS proxy, deploy/backup/restore scripts, `docs/deploy/` runbooks.
- **Not yet:** HTML/PDF extractors, live OSM Overpass/Google API fetchers, admin web UI.

Snapshot API routes return export metadata from `dataset_versions.manifest.exports` after `generate-exports` runs.

## Operational Shape

The service should remain lean:

- Local `.venv` for fast API and test work.
- Docker Compose for PostGIS, Redis, MinIO, workers, and VPS deployment.
- API is stateless.
- Postgres is the source of truth.
- Object storage holds private artifacts and generated public exports.
- Celery workers own crawling, imports, freshness checks, and snapshot generation.
