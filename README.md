# UK Jamaat Directory

Canonical public directory for UK mosques and jamaat timetable data.

**Status:** Fresh implementation. Phase 0/1 scaffolding is in progress; the authoritative product plan is in [PLAN.md](PLAN.md).

## Purpose

The Directory maintains mosque identities, source provenance, freshness status, schedule candidates, published jamaat occurrences, public read APIs, and bulk exports. It is designed to be useful to Sirat and other clients without depending on Sirat-specific journey-planning behavior.

The service owns public mosque and timetable truth. Sirat and other consumers should sync from the Directory through snapshots or change feeds, not call it live during journey planning.

## Stack

- Python 3.12
- FastAPI, Pydantic v2
- PostgreSQL 16 + PostGIS, SQLAlchemy async, Alembic
- Redis and Celery for background work
- S3-compatible object storage, with MinIO locally
- Docker Compose for reproducible local services and VPS deployment
- Local `.venv` workflow for fast day-to-day development

## Quick Start

```bash
cp .env.example .env
make install
docker compose up postgres redis minio -d
make migrate
make dev
```

API: http://localhost:8000

OpenAPI docs are available at http://localhost:8000/docs in non-production environments.

## Docker Stack

```bash
cp .env.example .env
docker compose up --build
```

The local compose stack runs the API, PostGIS, Redis, MinIO, a Celery worker, and Celery Beat.

## Development

```bash
make lint
make format
make test
make test-postgres
```

Use `make test` for fast unit tests. Use `make test-postgres` for tests that require PostGIS.

## Data Publication Rules

MyLocalMasjid is the intended primary source path, subject to explicit redistribution permission. Source data with `unknown`, `private_use_only`, or `blocked` publication policy must not enter public snapshots or public API responses.

Raw fetched artifacts, extraction runs, claim contact details, private admin notes, and restricted partner metadata are operational data and are not public export fields.

## GitHub Publishing

This repo is private initially. Before pushing:

1. Create a private GitHub repository.
2. Add the remote with `git remote add origin <repo-url>`.
3. Push with `git push -u origin main`.
4. Enable branch protection after CI passes reliably.
5. Add repository secrets only when production deployment needs them.

## License

Code is private/proprietary unless a later release changes this explicitly. Public data licensing will be documented separately before any public data release, likely with ODbL-compatible terms if OSM-derived data is included.
