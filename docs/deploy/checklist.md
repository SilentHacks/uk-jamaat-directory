# Deploy Checklist

Use this checklist for every production deploy. The automated script [`scripts/deploy/deploy.sh`](../../scripts/deploy/deploy.sh) follows the same order.

## Pre-deploy

- [ ] Changes reviewed and merged to the branch you deploy from
- [ ] CI green on the commit you are deploying
- [ ] `.env` on the server updated if new settings were added (compare with `.env.example` production section)
- [ ] Maintenance window communicated if migrations are breaking or downtime is expected

## Deploy steps

1. [ ] **Pull** latest code on the VPS (`git pull --ff-only`)
2. [ ] **Backup** Postgres (`./scripts/deploy/backup-postgres.sh`)
3. [ ] **Build** images (`docker compose -f docker-compose.production.yml build`)
4. [ ] **Migrate** database (`./scripts/deploy/migrate.sh`) — explicit step, never skip on schema changes
5. [ ] **Restart** services (`docker compose -f docker-compose.production.yml up -d`)
6. [ ] **Health** — API container healthy (`docker compose -f docker-compose.production.yml ps`)
7. [ ] **Smoke test** (`./scripts/deploy/smoke-test.sh`)
   - [ ] `GET /v1/health` returns 200
   - [ ] `GET /v1/health/ready` returns `{"status":"ok","database":"ok"}`
   - [ ] `GET /v1/mosques?limit=1` returns 200

Or run the full script:

```bash
./scripts/deploy/deploy.sh
```

## Post-deploy

- [ ] Check worker and beat logs for task errors
- [ ] If exports enabled, confirm latest manifest on `/v1/snapshots/latest`
- [ ] Note deploy time and commit SHA in your ops log

## Rollback

If smoke tests fail after migrate:

1. Stop api/worker/beat: `docker compose -f docker-compose.production.yml stop api worker beat`
2. Restore Postgres from the pre-deploy backup (see [restore.md](restore.md))
3. Checkout previous known-good commit and rebuild
4. Smoke test again before announcing recovery

If the failure is code-only and schema is unchanged, checking out the previous image/commit and restarting may be enough without a DB restore.

## Scheduled maintenance (not every deploy)

- [ ] Daily Postgres backup cron job present and logged
- [ ] Daily MinIO volume backup cron job present
- [ ] Backups copied off the VPS
- [ ] Quarterly restore drill completed (see [restore.md](restore.md))
