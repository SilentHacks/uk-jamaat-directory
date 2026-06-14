# Ubuntu VPS Deployment

Deploy the UK Jamaat Directory on a single Ubuntu VPS using Docker Compose, Caddy for automatic TLS, and named volumes for Postgres, Redis, and MinIO.

## Prerequisites

- Ubuntu 22.04 or 24.04 LTS
- Docker Engine and Docker Compose plugin (v2)
- A domain name pointing at the VPS (`A`/`AAAA` for `PUBLIC_DOMAIN`)
- Ports **80** and **443** open to the internet (for ACME and API traffic)
- **Do not** expose Postgres, Redis, or MinIO ports publicly

Install Docker (if needed):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in so the `docker` group applies.

## First-time setup

1. Clone the repository on the server:

```bash
git clone https://github.com/SilentHacks/uk-jamaat-directory.git
cd uk-jamaat-directory
```

2. Create production environment file (never commit this):

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `PUBLIC_DOMAIN` — public hostname (e.g. `directory.example.com`)
- `ACME_EMAIL` — email for Let's Encrypt expiry notices
- `PUBLIC_BASE_URL` — `https://<PUBLIC_DOMAIN>`
- `POSTGRES_PASSWORD` — strong random secret
- `ADMIN_API_KEY` — strong random secret
- `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` — MinIO credentials
- `ALLOWED_HOSTS` — same as `PUBLIC_DOMAIN`
- `EXPORT_BASE_URL` — public origin for export URLs (`https://<PUBLIC_DOMAIN>` when Caddy serves `/exports/*` from MinIO; use your CDN/R2/S3 base when external)
- `EXPORT_ENABLED` — leave `false` until export serving is configured; set `true` after verifying `/exports/*` is reachable (or external object storage is wired)

Ensure `DATABASE_URL` uses the same `POSTGRES_PASSWORD` and the `postgres` hostname (not `localhost`).

3. Start the stack:

```bash
docker compose -f docker-compose.production.yml up -d --build
```

4. Run migrations (explicit step — not automatic on container start):

```bash
./scripts/deploy/migrate.sh
```

5. Smoke test:

```bash
./scripts/deploy/smoke-test.sh
```

Caddy obtains TLS certificates automatically once DNS resolves and ports 80/443 are reachable.

## Architecture

```text
Internet
   │
   ▼
 Caddy :443 ──► api:8000 (internal only)
                  │
      ┌───────────┼───────────┐
      ▼           ▼           ▼
  postgres     redis       minio
      ▲
 worker / beat (Celery)
```

- **api** — stateless FastAPI; not published on the host except through Caddy
- **worker / beat** — Celery crawl, export, and scheduled tasks
- **postgres** — PostGIS; data in named volume `postgres_data`
- **redis** — Celery broker; named volume `redis_data`
- **minio** — S3-compatible object storage for artifacts and exports; named volume `minio_data`
- **caddy** — TLS termination, `/exports/*` → MinIO, and API reverse proxy

Local development continues to use `docker-compose.yml` (reload, host port 8000, Postgres on 54324).

## Routine deploys

Images are built and pushed to GHCR by CI on every merge to `master`. Deploys pull a
chosen tag; the server never builds. Trigger the **Deploy** GitHub Actions workflow
(`workflow_dispatch`, input `image_tag`), which SSHes in and runs the checklist script,
or run it directly on the server:

```bash
IMAGE_TAG=latest ./scripts/deploy/deploy.sh
```

This runs: source pull (if git checkout), pre-deploy Postgres backup, image pull,
migrations, service restart, health wait, and public smoke tests.

Skip steps when needed:

```bash
SKIP_BACKUP=1 ./scripts/deploy/deploy.sh      # no pre-deploy dump
SKIP_MIGRATE=1 ./scripts/deploy/deploy.sh     # schema unchanged
SKIP_SMOKE=1 ./scripts/deploy/deploy.sh       # no external curl checks
```

The deploy workflow needs these GitHub secrets: `DEPLOY_SSH_KEY` (a deploy user's
private key), `DEPLOY_HOST`, `DEPLOY_USER`, and `DEPLOY_KNOWN_HOSTS`. **Rollback:**
re-run the workflow with a previous `sha-<sha>` tag; if a migration was applied, restore
the pre-deploy dump first ([restore.md](restore.md)).

See [checklist.md](checklist.md) for the manual checklist.

## Uptime and error monitoring

Point an external monitor (UptimeRobot, healthchecks.io, BetterStack, …) at:

```
https://<PUBLIC_DOMAIN>/v1/health/ready
```

It returns `200` only when the database is reachable, and is exempt from the public rate
limit, so a 1–5 minute interval is safe. Alert on any non-`200`.

For error tracking, set `SENTRY_DSN` in `.env` (and optionally
`SENTRY_TRACES_SAMPLE_RATE`). The API and Celery workers report automatically; leaving
the DSN blank disables Sentry entirely.

## Backups

Schedule daily backups on the host with cron.

Postgres:

```bash
0 2 * * * cd /opt/uk-jamaat-directory && ./scripts/deploy/backup-postgres.sh >>/var/log/directory-backup.log 2>&1
```

MinIO volume:

```bash
30 2 * * * cd /opt/uk-jamaat-directory && ./scripts/deploy/backup-minio.sh >>/var/log/directory-backup.log 2>&1
```

Backups default to `backups/postgres/` and `backups/minio/` under the repo, with 14-day retention. Override with `BACKUP_DIR` and `RETENTION_DAYS`.

Copy backups off the VPS (object storage, another host, or backup provider) before relying on them for disaster recovery.

Restore procedure: [restore.md](restore.md).

## Host-local overrides

When the VPS already has a shared reverse proxy (or host nginx) that owns ports
80/443, add a gitignored `docker-compose.local.yml` on the server. Deploy
scripts pick it up automatically. See [local-overrides.md](local-overrides.md).

Do not commit operator-specific paths, usernames, or existing proxy site files.
Host runbooks may live under `.local/` on the server (also gitignored).

## Scaling path

The stack is already split into independently movable services:

| Component | Start here | Move later |
|-----------|------------|------------|
| API | VPS Compose | More replicas behind load balancer |
| Workers | VPS Compose | Horizontal Celery workers |
| Postgres | Named volume | Managed PostGIS or dedicated host |
| Redis | Named volume | Managed Redis |
| Object storage | MinIO volume | Cloudflare R2, AWS S3 (change `S3_*` env) |

Change `S3_ENDPOINT_URL` and credentials to point at external object storage without application code changes.

## Troubleshooting

**Caddy certificate errors** — confirm DNS, ports 80/443, and `PUBLIC_DOMAIN` in `.env`.

**502 from Caddy** — check API health: `docker compose -f docker-compose.production.yml logs api` and `docker compose -f docker-compose.production.yml ps`.

**Migrations fail** — ensure Postgres is healthy and `DATABASE_URL` matches `POSTGRES_PASSWORD`.

**Smoke test fails on `/v1/health/ready`** — Postgres connectivity; verify `DATABASE_URL` uses hostname `postgres`.
