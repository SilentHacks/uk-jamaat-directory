# UK Jamaat Directory Context

## Product Boundary

The UK Jamaat Directory is a public data utility. It owns canonical UK mosque identity records, linked source provenance, jamaat timetable occurrences, freshness status, public read APIs, contribution workflows, and bulk exports.

Sirat is a private journey-planning consumer. Sirat should sync Directory data into its own local read model and must not contain the Directory crawler, extraction, moderation, or publication infrastructure.

## Domain Language

- **Directory**: this public data service.
- **Directory Mosque ID**: stable public ID assigned by the Directory.
- **Source**: an external origin such as MyLocalMasjid, OSM, charity register, mosque website, standard feed, community submission, or partner feed.
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
- **Not yet:** OSM/charity discovery imports, candidate validation/publication workers, crawler, bulk NDJSON/CSV file generation, contribution/write APIs, admin moderation UI, Celery-backed pipelines.

Snapshot API routes expose metadata from `dataset_versions` (version, checksum, manifest export URLs). They do not generate export files until a later phase implements snapshot publishing.

## Operational Shape

The service should remain lean:

- Local `.venv` for fast API and test work.
- Docker Compose for PostGIS, Redis, MinIO, workers, and VPS deployment.
- API is stateless.
- Postgres is the source of truth.
- Object storage holds private artifacts and generated public exports.
- Celery workers own crawling, imports, freshness checks, and snapshot generation.
