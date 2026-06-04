# 0004: Local First, Docker Deployable

## Status

Accepted.

## Context

Day-to-day development should be quick. Rebuilding containers for every API or test change creates avoidable overhead.

The deployed service should still be easy to run on an Ubuntu VPS and move later to separate infrastructure.

## Decision

Support two first-class workflows:

- Local Python virtual environment for API work, tests, linting, and migrations.
- Docker Compose for local dependencies, full-stack smoke tests, workers, and VPS deployment.

The API, workers, scheduler, database, Redis, and object storage are configured as separate services.

## Consequences

Developers can run the API with `.venv` while keeping Postgres, Redis, and MinIO in Docker.

The production deployment can start as Docker Compose on a VPS and scale by moving Postgres, Redis, object storage, and workers independently later.
