# Agent Guide

## Commands

- Install local environment: `make install`
- Run API locally: `make dev`
- Run dependency services only: `docker compose up postgres redis minio -d`
- Run full stack: `docker compose up --build` or `make compose-up`
- Apply migrations: `make migrate`
- Lint: `make lint`
- Format: `make format`
- Unit tests: `make test` (~0.3s; skips PostGIS integration tests)
- PostGIS tests: see **PostGIS integration tests** below (do not run without preflight)
- Export OpenAPI/JSON schemas: `make export-contracts`

## Current Scope (implemented)

- FastAPI service under `/v1` with health, public read routes, and admin health
- PostGIS schema: mosques, sources, artifacts, candidates, occurrences, dataset versions, changes, moderation, claims, corrections
- Public read layer with `public_redistribution_allowed` source filtering
- Generated contracts in `docs/api/`
- GitHub Actions CI on `master`

- MyLocalMasjid ingest adapter (`import-mlm`, `report-mlm` CLI; synthetic fixtures in `data/fixtures/mylocalmasjid/`)
- Phase 6 discovery: shared identity matching, `import-osm`, admin mosque CRUD/merge, `POST /v1/contributions/mosques`, admin-only `POST /v1/admin/discovery-leads` (Google leads — never public)

Phase 6 scope excludes charity register import and public Google-derived facts. Do not add charity or Google as redistributable `mosque_sources` without an explicit ADR change.

Not implemented yet: publication pipeline (candidates → occurrences), bulk export files, Celery tasks, crawlers, frontend.

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

**Do not run `UK_JAMAAT_TEST_POSTGRES=1 make test-postgres` without preflight.** A misconfigured database causes a multi-minute hang that looks like tests are stuck.

### Why a bad run takes ~6 minutes

Integration tests use the function-scoped `db_engine` fixture in `tests/conftest.py`. Before each of the 11 PostGIS tests, `_wait_for_database()` retries connection up to **30 times** with a **1 second sleep** between failures (~32s per test). When the database is unreachable or credentials are wrong, every integration test pays that cost independently:

- 1 failing integration test ≈ **33 seconds** (observed)
- 11 failing integration tests ≈ **355 seconds / ~6 minutes** (observed 2026-06-04)

Pytest produces no useful output during each 30s wait, so the run appears hung.

### Common failure on shared dev machines

1. **Port 5432 already taken** by another project's Postgres container. `docker compose up postgres -d` may start, but with an **empty host port mapping** if `:5432` is unavailable. Tests still connect to `localhost:5432` and hit the wrong server.
2. **Wrong database name:** compose creates database `directory`; tests default to `directory_test` (must be created manually).
3. **URL mismatches:** `tests/conftest.py` and `README.md` default to port **5432**; `.env.example` uses port **5433** for `TEST_DATABASE_URL`.

Observed error when pointing at the wrong server: `asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "directory"`.

### Preflight checklist (run before `make test-postgres`)

```bash
# 0. Compose services reference .env — create it if missing
test -f .env || cp .env.example .env

# 1. See what owns host port 5432
docker ps --format '{{.Names}} {{.Ports}}' | grep 5432 || true
ss -ltnp | grep ':5432' || true

# 2. Start this project's Postgres and confirm it is healthy AND published on the host
docker compose up postgres -d
docker compose ps postgres
docker inspect "$(docker compose ps -q postgres)" --format '{{json .NetworkSettings.Ports}}'
# Expected: {"5432/tcp":[{"HostIp":"0.0.0.0","HostPort":"5432"}]}
# If Ports is {} — another container owns 5432; fix the conflict before running tests.

# 3. Create the test database (compose only creates `directory`)
docker compose exec -T postgres psql -U directory -d directory \
  -c "SELECT 1 FROM pg_database WHERE datname = 'directory_test'" \
  | grep -q 1 || \
docker compose exec -T postgres psql -U directory -d directory \
  -c "CREATE DATABASE directory_test;"

# 4. Quick connectivity probe (~1s). Must succeed before running the full suite.
.venv/bin/python - <<'PY'
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

url = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://directory:directory@localhost:5432/directory_test",
)
async def main() -> None:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await engine.dispose()
    print("postgres ok:", url)

asyncio.run(main())
PY

# 5. Full suite (typically ~5–15s when DB is correct)
UK_JAMAAT_TEST_POSTGRES=1 \
  TEST_DATABASE_URL=postgresql+asyncpg://directory:directory@localhost:5432/directory_test \
  make test-postgres
```

If step 4 fails, **stop** — do not run step 5. Fix port conflicts or credentials first.

### Agent timeouts

When blocking on PostGIS tests, allow at least **2 minutes** for a healthy run. If there is no pytest output progress for **>45 seconds**, treat it as a database misconfiguration (not a slow test) and run the preflight checklist instead of waiting the full ~6 minutes.

## Testing Expectations

- Add unit tests for normalization, validation, source policy gates, and freshness logic.
- Add integration tests for database-backed APIs and migrations (`tests/conftest.py` + `UK_JAMAAT_TEST_POSTGRES=1`).
- Add fixture tests for source adapters before importing real data.
- Add regression tests for DST, Ramadan schedules, multiple Jumuah sessions, and invalid jamaat ordering as those features land.
- Regenerate `docs/api/` when public response shapes change (`make export-contracts`).

## Commit Guidance

Keep commits reviewable. Prefer separate commits for schema changes, API behavior, and generated contract updates.
