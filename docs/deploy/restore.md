# Restore Drills

Practice restores on a staging VPS or local machine before relying on backups in production.

## Goals

- Confirm Postgres dumps are restorable and migrations are not required after restore (dump includes schema + data).
- Confirm MinIO volume backups contain artifact and export objects.
- Measure recovery time and document gaps.

Run a restore drill at least quarterly, or after any backup script change.

## Postgres restore

### Prerequisites

- A `.sql.gz` backup from `scripts/deploy/backup-postgres.sh`
- The stack stopped or Postgres willing to accept a destructive restore

### Steps

1. Stop writers so the database is quiesced:

```bash
docker compose -f docker-compose.production.yml stop api worker beat
```

2. Drop and recreate the database (destructive):

```bash
docker compose -f docker-compose.production.yml exec -T postgres \
  psql -U directory -d postgres -c "DROP DATABASE IF EXISTS directory;"
docker compose -f docker-compose.production.yml exec -T postgres \
  psql -U directory -d postgres -c "CREATE DATABASE directory;"
```

3. Restore from backup:

```bash
gunzip -c backups/postgres/directory-YYYYMMDDTHHMMSSZ.sql.gz \
  | docker compose -f docker-compose.production.yml exec -T postgres \
      psql -U directory -d directory
```

4. Restart services and smoke test:

```bash
docker compose -f docker-compose.production.yml up -d api worker beat caddy
./scripts/deploy/smoke-test.sh
```

5. Verify row counts and a known mosque/timetable spot-check via admin or SQL.

### Full volume reset (alternative)

If the dump is corrupt or you need a clean volume:

```bash
docker compose -f docker-compose.production.yml down
docker volume rm "$(docker compose -f docker-compose.production.yml volume ls -q | grep _postgres_data$)"
docker compose -f docker-compose.production.yml up -d postgres
# wait for healthy, then restore SQL as above
```

## MinIO restore

### Prerequisites

- A `minio-data-*.tar.gz` backup from `scripts/deploy/backup-minio.sh`
- MinIO stopped during restore

### Steps

1. Stop MinIO and dependent services:

```bash
docker compose -f docker-compose.production.yml stop api worker beat minio
```

2. Identify the volume:

```bash
volume_name="$(docker compose -f docker-compose.production.yml volume ls --format '{{.Name}}' | grep '_minio_data$' | head -n 1)"
echo "$volume_name"
```

3. Restore files into the volume:

```bash
docker run --rm \
  -v "${volume_name}:/data" \
  alpine:3.20 \
  sh -c "rm -rf /data/* && tar -xzf - -C /data" \
  < backups/minio/minio-data-YYYYMMDDTHHMMSSZ.tar.gz
```

4. Start services:

```bash
docker compose -f docker-compose.production.yml up -d
./scripts/deploy/smoke-test.sh
```

5. Verify an export manifest URL or artifact object exists in the bucket (admin CLI or MinIO inspection).

## Combined disaster recovery

Order for full stack loss on a new VPS:

1. Install Docker and clone the repo.
2. Copy `.env` from secure backup (not from git).
3. `docker compose -f docker-compose.production.yml up -d postgres redis minio`
4. Restore Postgres SQL dump.
5. Restore MinIO volume archive.
6. `docker compose -f docker-compose.production.yml up -d --build`
7. Run `./scripts/deploy/smoke-test.sh`
8. Confirm Celery beat schedules and latest export manifest.

Migrations are usually **not** needed after a full pg_dump restore. Run `./scripts/deploy/migrate.sh` only if the restored dump is from an older schema and you intentionally deploy newer code.

## Drill log template

Record each drill:

| Field | Value |
|-------|-------|
| Date | |
| Environment | staging / production-like |
| Backup files used | |
| Postgres restore time | |
| MinIO restore time | |
| Smoke test result | pass / fail |
| Issues found | |
| Follow-up actions | |
