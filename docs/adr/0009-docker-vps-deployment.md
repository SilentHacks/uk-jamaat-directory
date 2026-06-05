# 0009: Docker Compose VPS Deployment

## Status

Accepted.

## Context

Phases 0–10 established a local-first workflow (`.venv` + Docker dependencies) and a development-oriented `docker-compose.yml` with hot reload and host port bindings.

Production needs a reproducible Ubuntu VPS path with TLS, private database/object-store ports, explicit migrations, backups, and a documented restore drill — without blocking daily local development.

## Decision

1. **Keep `docker-compose.yml` for local development** — API reload, source mounts, Postgres on host port 54324, public dev ports for MinIO console.

2. **Add `docker-compose.vps.yml` as a standalone production stack** — no host bindings for Postgres/Redis/MinIO/API; Caddy on 80/443; `restart: unless-stopped`; production env defaults (`ENVIRONMENT=production`, `DOCS_ENABLED=false`, `TRUST_PROXY_HEADERS=true`).

3. **TLS via Caddy in Compose** — automatic certificates using `PUBLIC_DOMAIN` and `ACME_EMAIL` from server `.env`. Document nginx as an optional host-level alternative.

4. **Secrets only on the server** — `.env.vps.example` documents required variables; real `.env` is gitignored.

5. **Migrations are an explicit deploy step** — `scripts/deploy/migrate.sh` runs `alembic upgrade head` in a one-off API container; application containers do not auto-migrate on start.

6. **Named Docker volumes** for Postgres, Redis, and MinIO on the VPS.

7. **Backup scripts** — daily Postgres `pg_dump` and MinIO volume archive via host cron; 14-day local retention by default; off-site copy is operator responsibility.

8. **Deploy checklist** — `scripts/deploy/deploy.sh` and `docs/deploy/checklist.md` encode pull → backup → build → migrate → restart → smoke test.

## Consequences

- Developers keep the fast `.venv` loop unchanged.
- Operators follow `docs/deploy/ubuntu-vps.md` for first-time VPS setup.
- Restore drills are documented in `docs/deploy/restore.md`.
- Optional profiles (Playwright, OCR, observability) remain future work.
- Moving to managed Postgres or R2/S3 is an env-var and compose change, not an application rewrite.
