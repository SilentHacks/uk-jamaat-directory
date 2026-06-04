# Agent Guide

## Commands

- Install local environment: `make install`
- Run API locally: `make dev`
- Run all local services: `docker compose up --build`
- Apply migrations: `make migrate`
- Lint: `make lint`
- Format: `make format`
- Unit tests: `make test`
- PostGIS tests: `make test-postgres`

## Architecture Rules

- Keep Directory concerns in this repo: mosque identity, source provenance, schedule candidates, published occurrences, freshness, exports, and contribution/admin workflows.
- Do not add Sirat journey-planning, routing, user behavior, or private planner logic here.
- Public routes live under `/v1`.
- Use typed settings from `uk_jamaat_directory.config`.
- Use SQLAlchemy async models and Alembic migrations for schema changes.
- Keep raw source artifacts and private operational data out of public schemas and exports.

## Data Safety Rules

- Treat MyLocalMasjid and other partner/platform data as restricted until explicit redistribution permission is recorded.
- Do not commit real source dumps, raw artifacts, credentials, claim contact details, or generated private exports.
- Tests must use synthetic fixtures unless a fixture is explicitly documented as public and redistributable.
- Public export code must filter private fields by construction, not by ad hoc response trimming.

## Testing Expectations

- Add unit tests for normalization, validation, source policy gates, and freshness logic.
- Add integration tests for database-backed APIs and migrations.
- Add fixture tests for source adapters before importing real data.
- Add regression tests for DST, Ramadan schedules, multiple Jumuah sessions, and invalid jamaat ordering as those features land.

## Commit Guidance

Keep commits reviewable. Prefer one commit for repository baseline/setup changes and separate commits for behavior or schema changes.
