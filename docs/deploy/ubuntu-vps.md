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

1. Clone the repository on the server (private repo — use deploy keys or HTTPS with a token):

```bash
git clone git@github.com:SilentHacks/uk-jamaat-directory.git
cd uk-jamaat-directory
```

2. Create production environment file (never commit this):

```bash
cp .env.vps.example .env
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
docker compose -f docker-compose.vps.yml up -d --build
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

Use the deploy checklist script:

```bash
./scripts/deploy/deploy.sh
```

This runs: pull (if git checkout), build/up, pre-deploy Postgres backup, migrations, service restart, and public smoke tests.

Skip steps when needed:

```bash
SKIP_BACKUP=1 ./scripts/deploy/deploy.sh      # no pre-deploy dump
SKIP_MIGRATE=1 ./scripts/deploy/deploy.sh     # schema unchanged
SKIP_SMOKE=1 ./scripts/deploy/deploy.sh       # no external curl checks
```

See [checklist.md](checklist.md) for the manual checklist.

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

## nginx alternative

Caddy in Compose is the default path. For nginx on the host instead:

1. Publish the API on localhost only (custom compose override), or run nginx in Docker on the same network.
2. Use [deploy/nginx/directory.conf](../../deploy/nginx/directory.conf) as a starting point.
3. Obtain certificates with certbot before enabling HTTPS.

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

**502 from Caddy** — check API health: `docker compose -f docker-compose.vps.yml logs api` and `docker compose -f docker-compose.vps.yml ps`.

**Migrations fail** — ensure Postgres is healthy and `DATABASE_URL` matches `POSTGRES_PASSWORD`.

**Smoke test fails on `/v1/health/ready`** — Postgres connectivity; verify `DATABASE_URL` uses hostname `postgres`.
