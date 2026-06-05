#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/minio}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE="$BACKUP_DIR/minio-data-$TIMESTAMP.tar.gz"

cd "$ROOT_DIR"
eval "$("$ROOT_DIR/scripts/deploy/compose-args.sh")"

mkdir -p "$BACKUP_DIR"

volume_name="$(docker compose "${COMPOSE_ARGS[@]}" volume ls --format '{{.Name}}' | grep '_minio_data$' | head -n 1 || true)"

if [[ -z "$volume_name" ]]; then
  echo "error: could not find minio_data volume for ${COMPOSE_ARGS[*]}" >&2
  exit 1
fi

echo "Backing up Docker volume '$volume_name' to $ARCHIVE ..."

docker run --rm \
  -v "${volume_name}:/data:ro" \
  alpine:3.20 \
  tar -czf - -C /data . >"$ARCHIVE"

echo "MinIO volume backup written: $ARCHIVE"

if [[ "$RETENTION_DAYS" -gt 0 ]]; then
  find "$BACKUP_DIR" -name 'minio-data-*.tar.gz' -type f -mtime +"$RETENTION_DAYS" -delete
  echo "Pruned backups older than $RETENTION_DAYS days."
fi
