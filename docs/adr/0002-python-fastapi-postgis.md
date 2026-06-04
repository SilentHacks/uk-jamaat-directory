# 0002: Python FastAPI PostGIS Stack

## Status

Accepted.

## Context

The Directory needs geospatial mosque search, public JSON APIs, batch imports, validation-heavy schedule publication, background ingestion, and later extraction pipelines.

The sibling Sirat API already uses Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL/PostGIS, Docker Compose, and GitHub Actions successfully.

## Decision

Use:

- Python 3.12.
- FastAPI and Pydantic v2.
- SQLAlchemy async and Alembic.
- PostgreSQL 16 with PostGIS.
- Redis and Celery for background jobs.
- S3-compatible object storage with MinIO locally.
- Docker Compose for local dependencies and VPS deployment.

## Consequences

The stack aligns with Sirat, reducing future sync-adapter friction.

PostGIS remains available from day one for nearby search and identity matching. Celery and object storage can be lightly wired at first and expanded when crawling/extraction begins.
