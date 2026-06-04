# UK Jamaat Directory

Canonical public directory for UK mosques and jamaat timetable data.

**Status:** Early implementation. Phases 0–7 are in place (scaffolding, API shell, database schema, public read API, MyLocalMasjid import, discovery/canonicalization, schedule validation and publication). Crawlers and bulk export file generation are not implemented yet. The long-term product plan is in [PLAN.md](PLAN.md).

**Repository:** [github.com/SilentHacks/uk-jamaat-directory](https://github.com/SilentHacks/uk-jamaat-directory) (private)

## Purpose

The Directory maintains mosque identities, source provenance, freshness status, schedule candidates, published jamaat occurrences, public read APIs, and bulk exports. It is designed to be useful to Sirat and other clients without depending on Sirat-specific journey-planning behavior.

Sirat and other consumers should sync from the Directory through snapshots or change feeds, not call it live during journey planning.

## Stack

- Python 3.12, FastAPI, Pydantic v2
- PostgreSQL 16 + PostGIS, SQLAlchemy async, Alembic
- Redis and Celery (wired; background jobs not implemented yet)
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

Import OSM GB Muslim places of worship from synthetic fixtures and link sources to existing mosques before creating duplicates:

```bash
.venv/bin/uk-jamaat-directory import-osm \
  --input data/fixtures/openstreetmap/sample_places.json

# Import MLM after OSM so matching can link to existing mosques
.venv/bin/uk-jamaat-directory import-mlm \
  --input data/fixtures/mylocalmasjid/sample_export.json
```

Admin identity APIs (require `ADMIN_API_KEY`):

- `POST /v1/admin/mosques` — create mosque
- `PATCH /v1/admin/mosques/{id}` — update mosque
- `POST /v1/admin/mosques/{id}/sources` — attach source
- `POST /v1/admin/mosques/{id}/aliases` — add alias
- `POST /v1/admin/mosques/{id}/merge` — merge duplicate into canonical mosque
- `POST /v1/admin/discovery-leads` — record private Google/admin discovery lead (not public data)

Public community intake:

- `POST /v1/contributions/mosques` — submit a missing mosque for moderation (202 Accepted)

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
| 8+ | Admin candidate moderation API, crawlers, web UI | Planned |

Bulk export files are not produced yet. Snapshot endpoints return dataset metadata from `dataset_versions`; NDJSON/CSV files come in a later phase.

## Data Publication Rules

MyLocalMasjid is the intended primary source path, subject to explicit redistribution permission. Source data with `unknown`, `private_use_only`, or `blocked` publication policy must not enter public snapshots or public API responses.

Raw fetched artifacts, extraction runs, claim contact details, private admin notes, and restricted partner metadata are operational data and are not public export fields.

## Documentation

- [PLAN.md](PLAN.md) — full product architecture and rollout
- [CONTEXT.md](CONTEXT.md) — domain terms and publication invariants
- [AGENTS.md](AGENTS.md) — commands and conventions for contributors/agents
- [docs/adr/](docs/adr/) — architecture decisions
- [docs/api/](docs/api/) — generated public API contracts

## License

Code is private/proprietary unless a later release changes this explicitly. Public data licensing will be documented separately before any public data release, likely with ODbL-compatible terms if OSM-derived data is included.
