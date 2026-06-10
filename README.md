# UK Jamaat Directory

Canonical public directory for UK mosques and jamaat timetable data.

**Status:** Early implementation. Phases 0–12 are in place, plus repo-owned deterministic extractor scripts and an overnight AI authoring orchestrator (ADR 0016/0017). Admin web UI remains planned. The long-term product plan is in [PLAN.md](PLAN.md).

**Repository:** [github.com/SilentHacks/uk-jamaat-directory](https://github.com/SilentHacks/uk-jamaat-directory)

## Purpose

The Directory maintains mosque identities, source provenance, freshness status, schedule candidates, published jamaat occurrences, public read APIs, and bulk exports. It is designed to be useful to Sirat and other clients without depending on Sirat-specific journey-planning behavior.

Sirat and other consumers should sync from the Directory through snapshots or change feeds, not call it live during journey planning.

## Stack

- Python 3.12, FastAPI, Pydantic v2
- PostgreSQL 16 + PostGIS, SQLAlchemy async, Alembic
- Redis and Celery (worker + beat; crawl tasks when `CRAWL_ENABLED=true`)
- S3-compatible object storage (MinIO locally)
- Docker Compose for local services and VPS-style deployment
- Local `.venv` for fast API and test work

## Quick Start

### Local API (recommended for development)

```bash
cp .env.example .env
make install
docker compose up postgres redis minio -d
make migrate
make dev
```

- API: http://localhost:8000
- OpenAPI UI: http://localhost:8000/docs (non-production)
- MinIO console: http://localhost:9001

PostGIS is published on host port **54324** by default (not 5432) so it is less likely to collide with other local Postgres containers. Inside Docker networks the service still listens on `5432`.

### Full Docker stack

```bash
cp .env.example .env
docker compose up --build
```

Runs the API (with reload), PostGIS, Redis, MinIO, Celery worker, and Celery Beat.

Apply migrations from the host or inside the API container:

```bash
make migrate
```

## Public API (`/v1`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness and service metadata |
| `GET` | `/health/ready` | Readiness (Postgres connectivity) |
| `GET` | `/mosques` | List active mosques (`limit`, `offset`, `city`, `postcode`) |
| `GET` | `/mosques/search` | Search by `q`, `postcode`, and/or `city` (`limit`) |
| `GET` | `/mosques/{directory_mosque_id}` | Mosque detail with public source provenance |
| `GET` | `/mosques/{directory_mosque_id}/times` | Published occurrences (`from`, `to` dates) |
| `GET` | `/times/nearby` | Nearby published occurrences (`lat`, `lng`, `radius_m`, `date`) |
| `GET` | `/changes` | Change feed (`since` event id, `limit`) |
| `GET` | `/snapshots/latest` | Latest published snapshot metadata (`format=ndjson\|csv`) |
| `GET` | `/snapshots/{version}` | Snapshot metadata by version |

Public responses include provenance, confidence, and freshness where applicable. Rows from sources without `public_redistribution_allowed` are excluded from timetable endpoints.

Operational admin route (requires `X-Admin-Key` when `ADMIN_API_KEY` is set):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/health` | Admin-authenticated health check |

Full request/response shapes: [docs/api/openapi.json](docs/api/openapi.json) or `/docs` when running locally.

Regenerate exported contracts after API changes:

```bash
make export-contracts
```

See [docs/api/README.md](docs/api/README.md).

## MyLocalMasjid import (Phase 5)

Import synthetic or partner-provided exports into private sources, artifacts, and `schedule_candidates`. Default publication policy is `unknown` until redistribution is confirmed.

```bash
# Dry-run parse only
.venv/bin/uk-jamaat-directory import-mlm \
  --input data/fixtures/mylocalmasjid/sample_export.json \
  --dry-run

# Persist to local database (after migrate)
.venv/bin/uk-jamaat-directory import-mlm \
  --input data/fixtures/mylocalmasjid/sample_export.json \
  --publication-policy unknown

.venv/bin/uk-jamaat-directory report-mlm
.venv/bin/uk-jamaat-directory report-mlm --json
```

Supported formats: JSON bundle (`.json`), NDJSON (`.ndjson`), flat CSV (`.csv`). Do not commit real MyLocalMasjid dumps; use `data/fixtures/mylocalmasjid/` for tests only.

## Discovery import (Phase 6)

Export UK and Ireland Muslim places of worship from Overpass, import into Postgres, then import other discovery sources so matching can link to existing OSM mosques:

```bash
# Live OSM acquisition (writes gitignored data/exports/)
.venv/bin/uk-jamaat-directory export-osm --output data/exports/osm_uk_ie_muslim.json
.venv/bin/uk-jamaat-directory import-osm --input data/exports/osm_uk_ie_muslim.json

# Offline dev: use the synthetic import bundle instead
.venv/bin/uk-jamaat-directory import-osm \
  --input data/fixtures/openstreetmap/sample_places.json

# Import MiB after OSM so matching can link to existing mosques.
# Use --enrich-details for the full refresh (per-record Last Updated,
# phone, website, capacity, theme, data accuracy, source list); a CSV-only
# fetch is faster but leaves those fields empty.
.venv/bin/uk-jamaat-directory export-mib --enrich-details \
    --output data/exports/mib_uk_ie_mosques.json
.venv/bin/uk-jamaat-directory import-mib --input data/exports/mib_uk_ie_mosques.json
.venv/bin/uk-jamaat-directory report-mib

# Import MLM after OSM so matching can link to existing mosques
.venv/bin/uk-jamaat-directory import-mlm \
  --input data/fixtures/mylocalmasjid/sample_export.json
```

See [docs/data/import-order.md](docs/data/import-order.md) for the recommended import sequence and attribution notes.

Admin identity APIs (require `ADMIN_API_KEY`):

- `POST /v1/admin/mosques` — create mosque
- `PATCH /v1/admin/mosques/{id}` — update mosque
- `POST /v1/admin/mosques/{id}/sources` — attach source
- `POST /v1/admin/mosques/{id}/aliases` — add alias
- `POST /v1/admin/mosques/{id}/merge` — merge duplicate into canonical mosque
- `POST /v1/admin/discovery-leads` — record private Google/admin discovery lead (not public data)

## Admin moderation and reporting (Phase 8)

All admin routes require `X-Admin-Key`.

- `GET /v1/admin/candidates` — list schedule candidates (filter by status, source, mosque, date)
- `POST /v1/admin/candidates/{id}/approve` — approve a candidate for publication
- `POST /v1/admin/candidates/{id}/reject` — reject a candidate
- `GET /v1/admin/sources` — list sources
- `PATCH /v1/admin/sources/{id}` — update publication policy and source metadata
- `GET /v1/admin/coverage` — operational coverage summary
- `GET /v1/admin/source-health` — freshness and import health by source

Public community intake:

- `POST /v1/contributions/mosques` — submit a missing mosque for moderation (202 Accepted)
- `POST /v1/mosques/{id}/corrections` — report incorrect published data (202 Accepted)
- `POST /v1/mosques/{id}/schedule-submissions` — propose timetable rows as pending candidates
- `POST /v1/mosques/{id}/claims` — mosque ownership verification request (private contact details)

## Schedule validation and publication (Phase 7)

Imports create `schedule_candidates` only. To expose times on the public API, run validation then publication explicitly (no auto-publish on import).

```bash
# Optional: validate during import
.venv/bin/uk-jamaat-directory import-mlm \
  --input data/fixtures/mylocalmasjid/sample_export.json \
  --publication-policy public_redistribution_allowed \
  --validate

.venv/bin/uk-jamaat-directory validate-candidates
.venv/bin/uk-jamaat-directory publish-candidates
.venv/bin/uk-jamaat-directory recompute-freshness
```

Filters for validate/publish: `--source-id`, `--mosque-id`, `--from`, `--to`. Use `validate-candidates --dry-run` to inspect without status updates. Filtered publish merges into the latest snapshot: occurrences outside the filter are carried forward from the previous published dataset; only rows in scope are replaced or removed.

## Website crawl (Phase 9)

Mosque websites are fetched respectfully via `mosque_website` sources. The Directory registers crawl sources from active mosque `website_url` values (skipping mosques with recent MyLocalMasjid data), fetches homepage HTML, stores raw artifacts in MinIO, and awaits Phase 7/8 for AI profiling and deterministic extraction.

Crawl is **opt-in** (`CRAWL_ENABLED=false` by default). Requires MinIO/S3 for artifact bytes.

```bash
# Register mosque_website sources for mosques with website_url
.venv/bin/uk-jamaat-directory register-crawl-sources

# Fetch one source and store artifact (set CRAWL_ENABLED=true in .env)
.venv/bin/uk-jamaat-directory process-source --source-id <uuid> --force
```

Celery beat (when worker/beat containers run) registers sources daily and enqueues hourly due fetches. MyLocalMasjid is **not** crawled in Phase 9.

## Extractor scripts and overnight authoring

Timetable extraction from mosque websites uses repo-owned deterministic extractor scripts
under `src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts/`, authored by an
overnight AI orchestrator and gated by static validation, an execution smoke test, and
semantic output checks before deployment.

```bash
.venv/bin/uk-jamaat-directory orchestrate-authoring            # author scripts for pending sources
.venv/bin/uk-jamaat-directory smoke-test-repo-extractor \
  --extractor-key <key> --source-url <url>                     # run one script end to end
.venv/bin/uk-jamaat-directory prune-repo-extractors --apply    # retire broken/disallowed scripts
```

See [docs/adr/0016](docs/adr/0016-repo-owned-extractor-scripts.md),
[docs/adr/0017](docs/adr/0017-overnight-extractor-authoring-orchestrator.md), and
[AGENTS.md](AGENTS.md) for commands and conventions.

## Bulk exports (Phase 10)

After publishing, generate reproducible snapshot files for the latest (or specified) **published** dataset version. Files are stored in MinIO/S3 and manifest URLs/checksums are written to `dataset_versions.manifest.exports`.

```bash
# Latest published dataset version
.venv/bin/uk-jamaat-directory generate-exports

# Specific published version
.venv/bin/uk-jamaat-directory generate-exports --version 2026-06-04.1
```

Generated per version under `exports/{version}/`:

- `snapshot.ndjson` — mosques and occurrences (public-safe fields only)
- `occurrences.csv` — flat occurrence rows
- `changes.ndjson` — change events for the dataset version
- `metadata.json`, `attribution.txt`, `manifest.json`

`snapshot.ndjson` and `occurrences.csv` are byte-deterministic for a fixed database state. `metadata.json` and `manifest.json` include a `generated_at` timestamp and may differ between runs.

Set `EXPORT_BASE_URL` to the public object-storage or CDN endpoint that serves export blobs. The API does not proxy `/exports/*`; if unset, `PUBLIC_BASE_URL` is used. Export generation is opt-in (`EXPORT_ENABLED=false` by default). Re-running `generate-exports` for the same version is idempotent and overwrites prior objects.

`/v1/snapshots/latest` returns export URLs and checksums after generation. Celery beat runs `generate-exports` daily at 04:00 Europe/London when `EXPORT_ENABLED=true`.

## VPS deployment (Phase 11)

Production uses a separate Compose file with Caddy for TLS, internal-only Postgres/Redis/MinIO, and named volumes.

```bash
# On the server (after copying .env.example → .env and setting production secrets)
docker compose -f docker-compose.production.yml up -d --build
./scripts/deploy/migrate.sh
./scripts/deploy/smoke-test.sh
```

Routine deploys:

```bash
./scripts/deploy/deploy.sh
```

Documentation:

- [docs/deploy/ubuntu-vps.md](docs/deploy/ubuntu-vps.md) — first-time VPS setup
- [docs/deploy/checklist.md](docs/deploy/checklist.md) — deploy checklist
- [docs/deploy/restore.md](docs/deploy/restore.md) — backup restore drills

Daily backups (schedule via cron on the host):

```bash
./scripts/deploy/backup-postgres.sh
./scripts/deploy/backup-minio.sh
```

Local development continues to use `docker-compose.yml` (hot reload, Postgres on host port 54324).

## Development

```bash
make lint
make format
make test                    # unit tests only (~0.4s); skips PostGIS integration tests
make test-postgres-preflight # start Postgres, create directory_test, connectivity probe
make test-postgres           # preflight + full suite (needs PostGIS on localhost:54324)
make export-contracts
```

**PostGIS integration tests** use `localhost:54324` by default (see `docker-compose.yml`). The suite migrates the schema once per run and truncates tables between tests (not a full schema rebuild each time).

```bash
make test-postgres
```

Optional overrides:

```bash
export POSTGRES_HOST_PORT=54324
export TEST_DATABASE_URL=postgresql+asyncpg://directory:directory@localhost:54324/directory_test
make test-postgres
```

**Speed tips**

- Prefer `make test` during normal development; run `make test-postgres` before merge or when touching DB/migrations.
- Keep `docker compose up postgres -d` running between test runs to avoid container startup cost.
- `make test-postgres` runs preflight automatically; if the probe fails, fix port/URL issues before waiting on pytest.
- After changing `.env.example`, align `DATABASE_URL` / `TEST_DATABASE_URL` in your local `.env` to port `54324`.

CI runs lint, `alembic upgrade head`, and the full test suite against a PostGIS service container on pushes to `master`.

## Project Layout

```text
src/uk_jamaat_directory/   Application code (API, models, services, geo)
alembic/                   Database migrations
tests/                     Unit and PostGIS integration tests
docs/adr/                  Architecture decision records
docs/api/                  Generated OpenAPI and JSON Schema exports
docs/deploy/               Ubuntu VPS deployment, backups, restore drills
PLAN.md                    Product and rollout plan
CONTEXT.md                 Domain language and invariants
AGENTS.md                  Agent/developer conventions
```

## Implementation Progress

| Phase | Scope | Status |
|-------|--------|--------|
| 0 | Repo baseline, ADRs, hygiene | Done |
| 1 | Python/Docker scaffold, CI | Done |
| 2 | API shell (logging, errors, admin auth) | Done |
| 3 | PostGIS schema (mosques, sources, occurrences, …) | Done |
| 4 | Public read API and contract exports | Done |
| 5 | MyLocalMasjid adapter and `import-mlm` / `report-mlm` CLI | Done |
| 6 | Discovery sources, identity matching, admin/community intake | Done |
| 7 | Schedule validation, explicit publish CLI, freshness | Done |
| 8 | Admin moderation/reporting APIs, mosque contribution intake | Done |
| 9 | Standard feed crawl, artifacts, Celery tasks | Done |
| 10 | Bulk exports (NDJSON/CSV/changes/metadata) | Done |
| 11 | Docker VPS deployment, backups, restore drills | Done |
| 12 | GitHub publishing workflow (CI, Dependabot, license docs) | Done |
| 13+ | Admin web UI, HTML/PDF crawlers | Planned |

## Data Publication Rules

MyLocalMasjid is the intended primary source path, subject to explicit redistribution permission. Source data with `unknown`, `private_use_only`, or `blocked` publication policy must not enter public snapshots or public API responses.

Raw fetched artifacts, extraction runs, claim contact details, private admin notes, and restricted partner metadata are operational data and are not public export fields.

## Documentation

- [PLAN.md](PLAN.md) — full product architecture and rollout
- [CONTEXT.md](CONTEXT.md) — domain terms and publication invariants
- [AGENTS.md](AGENTS.md) — commands and conventions for contributors/agents
- [docs/adr/](docs/adr/) — architecture decisions
- [docs/api/](docs/api/) — generated public API contracts
- [docs/deploy/](docs/deploy/) — Ubuntu VPS deployment and operations
- [docs/github/](docs/github/) — CI, Dependabot, and branch protection notes

## License

| Artifact | Document |
|----------|----------|
| Application code | [LICENSE.md](LICENSE.md) — AGPL-3.0-or-later |
| Public normalized data (when released) | [DATA_LICENSE.md](DATA_LICENSE.md) — intended ODbL 1.0 |
| Attribution requirements | [ATTRIBUTION.md](ATTRIBUTION.md) |
| Security reports | [SECURITY.md](SECURITY.md) |

No public data release has occurred yet. See [docs/github/README.md](docs/github/README.md) for the GitHub workflow.
