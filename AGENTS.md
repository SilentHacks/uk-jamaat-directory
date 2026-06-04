# Agent Guide

## Commands

- Install local environment: `make install`
- Run API locally: `make dev`
- Run dependency services only: `docker compose up postgres redis minio -d`
- Run full stack: `docker compose up --build` or `make compose-up`
- Apply migrations: `make migrate`
- Lint: `make lint`
- Format: `make format`
- Unit tests: `make test`
- PostGIS tests: `UK_JAMAAT_TEST_POSTGRES=1 make test-postgres`
- Export OpenAPI/JSON schemas: `make export-contracts`

## Current Scope (implemented)

- FastAPI service under `/v1` with health, public read routes, and admin health
- PostGIS schema: mosques, sources, artifacts, candidates, occurrences, dataset versions, changes, moderation, claims, corrections
- Public read layer with `public_redistribution_allowed` source filtering
- Generated contracts in `docs/api/`
- GitHub Actions CI on `main`

- MyLocalMasjid ingest adapter (`import-mlm`, `report-mlm` CLI; synthetic fixtures in `data/fixtures/mylocalmasjid/`)

Not implemented yet: OSM/charity discovery imports, publication pipeline (candidates → occurrences), bulk export files, contribution/write APIs beyond admin stub, Celery tasks, crawlers, frontend.

## Architecture Rules

- Keep Directory concerns in this repo: mosque identity, source provenance, schedule candidates, published occurrences, freshness, exports, and contribution/admin workflows.
- Do not add Sirat journey-planning, routing, user behavior, or private planner logic here.
- Public routes live under `/v1`.
- Use typed settings from `uk_jamaat_directory.config`.
- Use SQLAlchemy async models and Alembic migrations for schema changes.
- Keep raw source artifacts and private operational data out of public schemas and exports.
- Map ORM rows to explicit public Pydantic models in `schemas/public.py`; do not return database models from public routes.

## Data Safety Rules

- Treat MyLocalMasjid and other partner/platform data as restricted until explicit redistribution permission is recorded.
- Do not commit real source dumps, raw artifacts, credentials, claim contact details, or generated private exports.
- Tests must use synthetic fixtures unless a fixture is explicitly documented as public and redistributable.
- Public export code must filter private fields by construction, not by ad hoc response trimming.

## Testing Expectations

- Add unit tests for normalization, validation, source policy gates, and freshness logic.
- Add integration tests for database-backed APIs and migrations (`tests/conftest.py` + `UK_JAMAAT_TEST_POSTGRES=1`).
- Add fixture tests for source adapters before importing real data.
- Add regression tests for DST, Ramadan schedules, multiple Jumuah sessions, and invalid jamaat ordering as those features land.
- Regenerate `docs/api/` when public response shapes change (`make export-contracts`).

## Commit Guidance

Keep commits reviewable. Prefer separate commits for schema changes, API behavior, and generated contract updates.
