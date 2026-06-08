# Agent Guide

## Commands

- Install local environment: `make install`
- Run API locally: `make dev`
- Run dependency services only: `docker compose up postgres redis minio -d`
- Run full stack: `docker compose up --build` or `make compose-up`
- VPS production stack: `docker compose -f docker-compose.production.yml up -d --build` (see `docs/deploy/ubuntu-vps.md`)
- Host-specific production overrides: gitignored `docker-compose.local.yml` on the server (see `docs/deploy/local-overrides.md`); never commit operator paths or proxy site files
- VPS deploy script: `make deploy` or `./scripts/deploy/deploy.sh`
- Apply migrations: `make migrate` (local) or `make deploy-migrate` (VPS)
- Lint: `make lint`
- Format: `make format`
- Unit tests: `make test` (~0.3s; skips PostGIS integration tests)
- PostGIS tests: `make test-postgres` (runs preflight first) — see **PostGIS integration tests** below
- Export OpenAPI/JSON schemas: `make export-contracts`
- Repo extractor flow: `list-repo-extractors`, `validate-repo-extractor(s)`, `sync-repo-extractors`, `process-source --source-id <uuid>`
- Overnight authoring: `orchestrate-authoring [--concurrency N --limit N --source-id UUID --dry-run]`. Requires the `opencode` binary on PATH and `CRAWL_ENABLED=true`. Set `OPENAI_BASE_URL` / `OPENAI_API_KEY` (auto-populated from `ai_agent_base_url` / `ai_agent_api_key`) to route the OpenCode agent to a real provider. PDF/Image targets are skipped to the review queue automatically.

## Current Scope (implemented)

- FastAPI service under `/v1` with health, public read routes, and admin health
- PostGIS schema: mosques, sources, artifacts, candidates, occurrences, dataset versions, changes, moderation, claims, corrections
- Public read layer with `public_redistribution_allowed` source filtering
- Generated contracts in `docs/api/`
- GitHub Actions CI on `master`

- MyLocalMasjid ingest adapter (`import-mlm`, `report-mlm` CLI; synthetic fixtures in `data/fixtures/mylocalmasjid/`)
- Phase 6 discovery: shared identity matching, `export-osm` + `import-osm`, `export-mib` + `import-mib` + `report-mib`, admin mosque CRUD/merge, `POST /v1/contributions/mosques`, admin-only `POST /v1/admin/discovery-leads` (Google leads — never public)

Phase 6 scope excludes charity register import and public Google-derived facts. Do not add charity or Google as redistributable `mosque_sources` without an explicit ADR change.

- Phase 7 schedules: `validate-candidates`, `publish-candidates`, `recompute-freshness` CLI; explicit publish only (see ADR 0006)
- Phase 8 admin: candidate approve/reject/list, source list/patch, coverage, source-health; public corrections, schedule submissions, and claims on `/v1/mosques/{id}/…`
- Phase 7 AI replaced by repo-owned deterministic extractor scripts (ADR 0016): Python modules under `ingest/extract/repo_extractors/scripts/` are the source of truth. CLIs `list-repo-extractors`, `validate-repo-extractor(s)`, `sync-repo-extractors`, `process-source` consume repo scripts; admin API `GET/POST /v1/admin/sources/{id}/extractor` exposes assignments. Scheduled runtime is sandboxed with no network access; passing static, capability, output, and candidate validation gates activates a script.
- Phase 7b overnight authoring orchestrator (ADR 0017): CLI `orchestrate-authoring` (and Celery beat `authoring.run_overnight` at 02:00 Europe/London) discovers prayer-timetable pages for `mosque_website` sources without an active assignment, calls the OpenCode CLI as a subprocess (`opencode -m <model> run --format json <prompt>`), validates the returned Python against the same gates as `validate-repo-extractor`, writes the script to `ingest/extract/repo_extractors/scripts/`, then runs `sync-repo-extractors` to create the assignment. PDF / image / OCR / rendered-JS targets are skipped to a review queue (`extractor_authoring_tasks.status = skipped_review`). Status visible at `GET /v1/admin/authoring`. The agent only sees the source URL, the discovered target URL, and a trimmed HTML sample (max 16 KB). OCR / PDF / browser rendering are explicitly out of scope (see ADR 0017).
- Phase 9 crawl: mosque_website fetch, private S3 artifacts, Celery tasks (`register_sources`, `fetch_due_sources`, `process_source`), CLI (`register-crawl-sources`, `process-source`, …). HTML/PDF/OCR deferred.
- Phase 10 exports: `generate-exports` CLI, Celery `exports.generate_latest`, NDJSON/CSV/changes/metadata files in S3 with manifest checksums (ADR 0008).
- Phase 11 deploy: `docker-compose.production.yml`, bundled Caddy TLS, `scripts/deploy/*` (migrate, backup, deploy, smoke), `docs/deploy/` (ADR 0009).
- Phase 12 GitHub: CI on `master`, Dependabot, dependency review workflow, `LICENSE.md` / `DATA_LICENSE.md` / `ATTRIBUTION.md` / `SECURITY.md`, `docs/github/` (ADR 0010).

Not implemented yet: HTML/PDF crawlers, frontend.

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

## PostGIS integration tests (agent notes)

**Default for most changes:** run `make test` only. It completes in under a second and is enough for adapter, policy, and API-layer work that does not touch DB fixtures.

**Prefer `make test-postgres`** (not raw `pytest` with `UK_JAMAAT_TEST_POSTGRES=1`) so preflight runs and URLs default to port **54324**.

### Local Postgres port

Directory compose publishes PostGIS on host port **54324** → container `5432`. Defaults are aligned in `docker-compose.yml`, `.env.example`, `config.py`, `tests/conftest.py`, and `Makefile` (`POSTGRES_HOST_PORT`).

This avoids the common case where another project's Postgres already owns **5432** or **5433**.

### Speed (what changed)

Integration tests use a **session-scoped** `db_engine` fixture: one schema drop/create, one `alembic upgrade head` per pytest run. Each test gets a clean database via **TRUNCATE** (not a full remigration).

Typical healthy run: **~15–40s** for the full PostGIS suite, depending on machine and cold vs warm Postgres.

**Ways to go faster**

- Use `make test` unless the change touches DB-backed routes, migrations, or ingest persistence.
- Keep `docker compose up postgres -d` running between runs.
- Do not point `TEST_DATABASE_URL` at the wrong host/port (wastes time on connection retries).
- Tune startup wait only when needed: `UK_JAMAAT_TEST_DB_WAIT_ATTEMPTS=5 UK_JAMAAT_TEST_DB_WAIT_SECONDS=0.2`.
- Skip schema rebuild when iterating: `UK_JAMAAT_TEST_REBUILD=0 make test-postgres` (reuses existing migrated schema; still truncates per test).

### When a bad run still hangs

If Postgres is unreachable, `_wait_for_database()` retries up to **10 times** with **0.5s** sleep (~5s total at session start). Older function-scoped remigration multiplied that per test; session scope limits the pain to one startup wait.

**Do not run integration tests without preflight** when the database has never been started on this machine.

### Preflight

```bash
make test-postgres-preflight
# or the full suite (preflight + pytest):
make test-postgres
```

Manual checklist if compose fails:

```bash
test -f .env || cp .env.example .env

docker compose up postgres -d
docker compose ps postgres
docker inspect "$(docker compose ps -q postgres)" --format '{{json .NetworkSettings.Ports}}'
# Expected host mapping includes "HostPort":"54324"

docker compose exec -T postgres psql -U directory -d directory \
  -c "SELECT 1 FROM pg_database WHERE datname = 'directory_test'" \
  | grep -q 1 || \
docker compose exec -T postgres psql -U directory -d directory \
  -c "CREATE DATABASE directory_test;"

POSTGRES_HOST_PORT=54324 make test-postgres-preflight
```

If the probe fails, **stop** — do not run pytest hoping it will recover.

### Agent timeouts

When blocking on PostGIS tests, allow at least **90 seconds** for a healthy run. If there is no pytest output progress for **>45 seconds** after preflight succeeded, investigate DB locks or a stuck container — not normal slowness.

## Testing Expectations

- Add unit tests for normalization, validation, source policy gates, and freshness logic.
- Add integration tests for database-backed APIs and migrations (`tests/conftest.py` + `make test-postgres`).
- Add fixture tests for source adapters before importing real data.
- Add regression tests for DST, Ramadan schedules, multiple Jumuah sessions, and invalid jamaat ordering as those features land.
- Regenerate `docs/api/` when public response shapes change (`make export-contracts`).

## Commit Guidance

Keep commits reviewable. Prefer separate commits for schema changes, API behavior, and generated contract updates.
