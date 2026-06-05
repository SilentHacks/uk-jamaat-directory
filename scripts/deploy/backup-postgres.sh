#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$BACKUP_DIR/directory-$TIMESTAMP.sql.gz"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

echo "Backing up Postgres to $ARCHIVE ..."
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  pg_dump -U directory -d directory --no-owner --no-acl \
  | gzip -9 >"$ARCHIVE"

echo "Postgres backup written: $ARCHIVE"

if [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$BACKUP_DIR" -name 'directory-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -delete
  echo "Pruned backups older than $RETENTION_DAYS days."
fi
